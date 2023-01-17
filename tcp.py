import asyncio
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
            flags, window_size, checksum, urg_ptr = read_header(segment)

        if dst_port != self.porta:
            # Ignora cabecalhos que não são destinados à porta do nosso servidor
            return
        if not self.rede.ignore_checksum and calc_checksum(segment, src_addr, dst_addr) != 0:
            print('descartando cabecalho com checksum incorreto')
            return

        payload = segment[4*(flags >> 12):]
        id_conexao = (src_addr, src_port, dst_addr, dst_port)

        if (flags & FLAGS_SYN) == FLAGS_SYN:
            # A flag SYN estar setada significa que é um cliente tentando estabelecer uma conexão nova
            # TODO: talvez você precise passar mais coisas para o construtor de conexão
            # Criando flags
            flags = flags & 0
            flags = flags | (FLAGS_SYN | FLAGS_ACK)
            conexao = self.conexoes[id_conexao] = Conexao(self,
                                                          id_conexao, seq_no=SystemRandom().randint(0, 0xffff), ack_no=seq_no + 1,
                                                          flags=flags,
                                                          src_port=src_port,
                                                          dst_port=dst_port,
                                                          src_addr=src_addr,
                                                          dst_addr=dst_addr)
            # TODO: você precisa fazer o handshake aceitando a conexão. Escolha se você acha melhor

            # fazer aqui mesmo ou dentro da classe Conexao.
            if self.callback:
                self.callback(conexao)
        elif id_conexao in self.conexoes:
            # Passa para a conexão adequada se ela já estiver estabelecida
            self.conexoes[id_conexao]._rdt_rcv(seq_no, ack_no, flags, payload)
        else:
            print('%s:%d -> %s:%d (pacote associado a conexão desconhecida)' %
                  (src_addr, src_port, dst_addr, dst_port))


class Conexao:
    """ 

    Passando tudo como argumento da classe como uma maneira burra de fazer pra mudar em relacao ao codido do joao

    """

    def __init__(self, servidor, id_conexao, seq_no, ack_no, flags, src_port, dst_port, src_addr, dst_addr):
        self.servidor = servidor
        self.id_conexao = id_conexao
        self.callback = None
        # um timer pode ser criado assim; esta linha é só um exemplo e pode ser removida
        self.timer = asyncio.get_event_loop().call_later(1, self._exemplo_timer)
        # self.timer.cancel()   # é possível cancelar o timer chamando esse método; esta linha é só um exemplo e pode ser removida
        self.seq_no = seq_no
        self.ack_no = ack_no
        self.seq_no_base = self.seq_no

        # Invertento endereço de origem e de destino
        aux = src_port
        src_port = dst_port
        dst_port = aux

        aux = src_addr
        src_addr = dst_addr
        dst_addr = aux

        # Construindo cabeçalho com flags SYN e ACK
        cabecalho = make_header(src_port,
                                dst_port,
                                self.seq_no,
                                self.ack_no,
                                flags)
        cabecalho_checksum_corrigido = fix_checksum(cabecalho,
                                                    src_addr,
                                                    dst_addr)
        servidor.rede.enviar(cabecalho_checksum_corrigido, dst_addr)

        # Incrementando seq_no para considerar o SYN enviado
        self.seq_no += 1

    def _exemplo_timer(self):
        # Esta função é só um exemplo e pode ser removida
        print('Este é um exemplo de como fazer um timer')

    def _rdt_rcv(self, seq_no, ack_no, flags, payload):
        # TODO: trate aqui o recebimento de cabecalhos provenientes da camada de rede.
        # Chame self.callback(self, dados) para passar dados para a camada de aplicação após
        # garantir que eles não sejam duplicados e que tenham sido recebidos em ordem.
        print('recebido payload: %r' % payload)

        # Verificando se o pacote não é duplicado ou está fora de ordem
        if seq_no != self.ack_no:
            return

        # Se for um ACK, é preciso encerrar o timer e remover da lista de pacotes
        # que precisam ser confirmados
        """ if (flags & FLAGS_ACK) == FLAGS_ACK and ack_no > self.seq_no_base:
            self.seq_no_base = ack_no
            if self.pacotes_sem_ack:
                self._atualizar_timeout_interval()
                self.timer.cancel()
                self.pacotes_sem_ack.pop(0)
                if self.pacotes_sem_ack:
                    self.timer = asyncio.get_event_loop().call_later(
                        self.timeoutInterval, self._timer)

        # Se for um pedido de encerrar a conexão
        if (flags & FLAGS_FIN) == FLAGS_FIN:
            payload = b''
            self.ack_no += 1
        elif len(payload) <= 0:
            return """

        self.callback(self, payload)
        self.ack_no += len(payload)

        # Construindo e enviando pacote ACK
        dst_addr, dst_port, src_addr, src_port = self.id_conexao

        segmento = make_header(src_port,
                               dst_port,
                               self.seq_no_base, self.ack_no, FLAGS_ACK)
        segmento_checksum_corrigido = fix_checksum(
            segmento, src_addr, dst_addr)

        self.servidor.rede.enviar(segmento_checksum_corrigido, dst_addr)
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
        # TODO: implemente aqui o envio de dados.
        # Chame self.servidor.rede.enviar(cabecalho, dest_addr) para enviar o cabecalho
        # que você construir para a camada de rede.
        pass

    def fechar(self):
        """
        Usado pela camada de aplicação para fechar a conexão
        """
        # TODO: implemente aqui o fechamento de conexão
        pass
