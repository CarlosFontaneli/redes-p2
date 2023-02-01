import asyncio
import time
from tcputils import *
from random import randint, SystemRandom


class Servidor:
    def __init__(self, rede, porta):
        self.rede = rede
        self.porta = porta
        self.conexoes = {}
        self.callback = None
        self.rede.registrar_recebedor(self._rdt_rcv)

    def registrar_monitor_de_conexoes_aceitas(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que uma nova conexão for aceita
        """
        self.callback = callback

    def _rdt_rcv(self, src_addr, dst_addr, segment):
        src_port, dst_port, seq_no, ack_no, \
            flags, _, _, _ = read_header(segment)

        if dst_port != self.porta:
            # Ignora segmentos que não são destinados à porta do nosso servidor
            return
        if ~(self.rede.ignore_checksum) and calc_checksum(segment, src_addr, dst_addr) != 0:
            print('descartando segmento com checksum incorreto')
            return

        payload = segment[4*(flags >> 12):]
        id = (src_addr, src_port, dst_addr, dst_port)

        if (flags & FLAGS_SYN) == FLAGS_SYN:
            flags = flags & 0
            flags = flags | (FLAGS_SYN | FLAGS_ACK)
            self.conexoes[id] = Conexao(self,
                                        id, seq_no=SystemRandom().randint(0, 0xffff), ack_no=seq_no + 1,
                                        flags=flags,
                                        src_port=src_port,
                                        dst_port=dst_port,
                                        src_addr=src_addr,
                                        dst_addr=dst_addr)

            # conexao = self.conexoes[id]

            if self.callback:
                self.callback(self.conexoes[id])
        elif id in self.conexoes:
            # Passa para a conexão adequada se ela já estiver estabelecida
            self.conexoes[id]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (pacote associado a conexão desconhecida)' %
                  (src_addr, src_port, dst_addr, dst_port))

    """ def _fechar_conexao(self, id):
        if id in self.conexoes:
            del self.conexoes[id] """


class Conexao:
    def __init__(self, servidor, id, seq_no, ack_no, flags, src_port, dst_port, src_addr, dst_addr):
        self.servidor = servidor
        self.id = id
        self.seq_no = seq_no
        self.ack_no = ack_no
        self.callback = None
        self.timer = None
        self.seq_no_base = None
        self.no_ack = []
        self.timeout = 1
        self.devRTT = None
        self.estimated_rtt = None
        self.fila_envio = []

        # Invertento endereço de origem e de destino
        aux = src_port
        src_port = dst_port
        dst_port = aux
        self.timeout = 1
        aux = src_addr
        src_addr = dst_addr
        dst_addr = aux

        # Construindo cabeçalho com flags SYN e ACK
        segmento = make_header(src_port,
                               dst_port,
                               self.seq_no,
                               self.ack_no, flags)
        cabecalho = fix_checksum(segmento,
                                 src_addr,
                                 dst_addr)
        self.servidor.rede.enviar(cabecalho, dst_addr)

        # Incrementando seq_no para considerar o SYN enviado
        self.seq_no += 1
        self.seq_no_base = self.seq_no

    def timer_function(self):
        if len(self.no_ack):
            #segmento, _, dst_addr, _ = self.no_ack[0]
            segmento = self.no_ack[0][0]
            dst_addr = self.no_ack[0][2]
            # Reenviando pacote
            self.servidor.rede.enviar(segmento, dst_addr)
            self.no_ack[0][3] = None

    def update_timeout(self):
        #_, _, _, sample_rtt = self.no_ack[0]
        sample_rtt = self.no_ack[0][3]
        if sample_rtt == None:
            return

        sample_rtt = round(time.time(), 3) - sample_rtt
        if self.estimated_rtt == None:
            self.estimated_rtt = sample_rtt
            self.devRTT = sample_rtt/2
        else:
            self.estimated_rtt = 0.875*self.estimated_rtt + 0.125*sample_rtt
            self.devRTT = 0.75*self.devRTT + 0.25 * \
                abs(sample_rtt-self.estimated_rtt)

        self.timeout = self.estimated_rtt + 4 * self.devRTT

    def _rdt_rcv(self, seq_no, ack_no, flags, payload):
        print('recebido payload: %r' % payload)

        # Verificando se o pacote não é duplicado ou está fora de ordem
        """ if seq_no != self.ack_no:
            return """

        # Se for um ACK, é preciso encerrar o timer e remover da lista de pacotes
        # que precisam ser confirmados
        if (flags & FLAGS_ACK) == FLAGS_ACK:
            if ack_no > self.seq_no_base:
                self.seq_no_base = ack_no
                if self.no_ack != 0:
                    self.update_timeout()
                    self.timer.cancel()
                    self.no_ack.pop(0)
                    if self.no_ack:
                        self.timer = asyncio.get_event_loop().call_later(
                            self.timeout, self.timer_function)

        # Se for um pedido de encerrar a conexão
        if (flags & FLAGS_FIN) == FLAGS_FIN:
            payload = b''
            self.ack_no += 1
        elif len(payload) <= 0:
            return

        self.callback(self, payload)
        self.ack_no += len(payload)

        # Construindo e enviando pacote ACK
        #dst_addr, dst_port, src_addr, src_port = self.id
        dst_addr = self.id[0]
        dst_port = self.id[1]
        src_addr = self.id[2]
        src_port = self.id[3]

        segmento = make_header(
            src_port, dst_port, self.seq_no_base, self.ack_no, FLAGS_ACK)
        cabecalho = fix_checksum(segmento,
                                 src_addr,
                                 dst_addr)

        self.servidor.rede.enviar(cabecalho, dst_addr)

    # Os métodos abaixo fazem parte da API

    def registrar_recebedor(self, callback):
        """
        Usado pela camada de aplicação para registrar uma função para ser chamada
        sempre que dados forem corretamente recebidos
        """
        self.callback = callback

    def enviar(self, dados):
        """
        Usado pela camada de aplicação para enviar dados
        """
        # Construindo e enviando pacotes
        #dst_addr, dst_port, src_addr, src_port = self.id
        dst_addr = self.id[0]
        dst_port = self.id[1]
        src_addr = self.id[2]
        src_port = self.id[3]

        flags = 0 | FLAGS_ACK

        """ for i in range(int(len(dados)/MSS)):
            ini = i*MSS
            fim = min(len(dados), (i+1)*MSS) """
        intervalo = int(len(dados)/MSS)
        for i in range(intervalo):
            inicio = i*MSS
            fim = 0
            if len(dados) < (i+1)*MSS:
                fim = len(dados)
            else:
                fim = (i+1)*MSS
            payload = dados[inicio:fim]

            segmento = make_header(src_port,
                                   dst_port,
                                   self.seq_no,
                                   self.ack_no,
                                   flags)
            cabecalho = fix_checksum(segmento+payload,
                                     src_addr,
                                     dst_addr)
            self.servidor.rede.enviar(cabecalho, dst_addr)

            self.timer = asyncio.get_event_loop().call_later(self.timeout,
                                                             self.timer_function)
            self.no_ack.append([cabecalho,
                                len(payload),
                                dst_addr,
                                round(time.time(), 5)])

            # Atualizando seq_no com os dados recém enviados
            self.seq_no += len(payload)

    def fechar(self):
        """
        Usado pela camada de aplicação para fechar a conexão
        """
        # Construindo e enviando pacote FYN
        #dst_addr, dst_port, src_addr, src_port = self.id
        dst_addr = self.id[0]
        dst_port = self.id[1]
        src_addr = self.id[2]
        src_port = self.id[3]

        segmento = make_header(src_port,
                               dst_port,
                               self.seq_no,
                               self.ack_no,
                               FLAGS_FIN)
        cabecalho = fix_checksum(segmento,
                                 src_addr,
                                 dst_addr)

        self.servidor.rede.enviar(cabecalho, dst_addr)
        del self.servidor.conexoes[self.id]
