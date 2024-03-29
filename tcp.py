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
        self.callback = callback

    def _rdt_rcv(self, src_addr, dst_addr, segment):
        src_port, dst_port, seq_no, ack_no, \
            flags, _, _, _ = read_header(segment)

        if dst_port != self.porta:
            return
        if (not self.rede.ignore_checksum) and calc_checksum(segment, src_addr, dst_addr) != 0:
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

            if self.callback:
                self.callback(self.conexoes[id])
        elif id in self.conexoes:
            # Passa para a conexão adequada se ela já estiver estabelecida
            self.conexoes[id]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (pacote associado a conexão desconhecida)' %
                  (src_addr, src_port, dst_addr, dst_port))


class Conexao:
    def __init__(self, servidor, id, seq_no, ack_no, flags, src_port, dst_port, src_addr, dst_addr):
        print('criando objeto Conexao com seq_no=', seq_no)
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

        aux = src_port
        src_port = dst_port
        dst_port = aux
        self.timeout = 1
        aux = src_addr
        src_addr = dst_addr
        dst_addr = aux

        segmento = make_header(src_port,
                               dst_port,
                               self.seq_no,
                               self.ack_no, flags)
        cabecalho = fix_checksum(segmento,
                                 src_addr,
                                 dst_addr)
        self.servidor.rede.enviar(cabecalho, dst_addr)

        self.seq_no += 1
        self.seq_no_base = self.seq_no

    def timer_function(self):
        if len(self.no_ack):
            segmento = self.no_ack[0][0]
            dst_addr = self.no_ack[0][2]
            self.servidor.rede.enviar(segmento, dst_addr)
            self.no_ack[0][3] = None

    def update_timeout(self):

        if len(self.no_ack) == 0:
            return
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

        if seq_no != self.ack_no:
            return

        if (flags & FLAGS_ACK) == FLAGS_ACK:
            if ack_no > self.seq_no_base:
                self.seq_no_base = ack_no
                if self.no_ack != 0:
                    self.update_timeout()
                    if self.timer is not None:
                        self.timer.cancel()
                    if self.no_ack:
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

        segmento = make_header(
            self.id[3], self.id[1], self.seq_no_base, self.ack_no, FLAGS_ACK)
        cabecalho = fix_checksum(segmento,
                                 self.id[2],
                                 self.id[0])

        self.servidor.rede.enviar(cabecalho, self.id[0])

    # Os métodos abaixo fazem parte da API

    def registrar_recebedor(self, callback):
        self.callback = callback

    def enviar(self, dados):
        """
        Usado pela camada de aplicação para enviar dados
        """

        flags = 0 | FLAGS_ACK

        intervalo = (len(dados)+MSS-1)//MSS
        print('entrou em enviar', dados)
        for i in range(intervalo):
            print('enviar iteracao', i)
            inicio = i*MSS
            fim = 0
            if len(dados) < (i+1)*MSS:
                fim = len(dados)
            else:
                fim = (i+1)*MSS
            payload = dados[inicio:fim]

            print('montando com seq_no', self.seq_no)
            segmento = make_header(self.id[3],
                                   self.id[1],
                                   self.seq_no,
                                   self.ack_no,
                                   flags)
            cabecalho = fix_checksum(segmento+payload,
                                     self.id[2],
                                     self.id[0])
            print('enviando', cabecalho)
            self.servidor.rede.enviar(cabecalho, self.id[0])

            self.timer = asyncio.get_event_loop().call_later(self.timeout,
                                                             self.timer_function)
            self.no_ack.append([cabecalho,
                                len(payload),
                                self.id[0],
                                round(time.time(), 5)])

            # Atualizando seq_no com os dados recém enviados
            self.seq_no += len(payload)

    def fechar(self):
        """
        Usado pela camada de aplicação para fechar a conexão
        """

        segmento = make_header(self.id[3],
                               self.id[1],
                               self.seq_no,
                               self.ack_no,
                               FLAGS_FIN)
        cabecalho = fix_checksum(segmento,
                                 self.id[2],
                                 self.id[0])

        self.servidor.rede.enviar(cabecalho, self.id[0])
        del self.servidor.conexoes[self.id]
