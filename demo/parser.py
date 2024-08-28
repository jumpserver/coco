import logging
import re
import pyte


logger = logging.getLogger(__name__)
BACKSPACE_CHAR = {b'\x08': b'\x08\x1b[K', b'\x7f': b'\x08\x1b[K'}
ENTER_CHAR = [b'\r', b'\n', b'\r\n']
ENTER_CHAR_ORDER = [ord(b'\r'), ord(b'\n')]
CLEAR_LINE_CHAR = b'\x15'
UNSUPPORTED_CHAR = {b'\x15': 'Ctrl-U', b'\x0c': 'Ctrl-L', b'\x05': 'Ctrl-E'}
CLEAR_CHAR = b'\x1b[H\x1b[2J'
BELL_CHAR = b'\x07'
NEW_LINE = b'\r\n'
RZ_PROTOCOL_CHAR = b'**\x18B0900000000a87c\r\x8a\x11'
PS1_PATTERN = re.compile(r'\[?.*@.*\]?[\$#]')


class SizedList(list):
    def __init__(self, maxsize=0):
        self.maxsize = maxsize
        self.size = 0
        self.end_with_ascii = False
        super().__init__()

    def is_full(self):
        if self.maxsize == 0:
            return False
        if not self.end_with_ascii:
            return False
        if self.size >= self.maxsize:
            return True
        else:
            return False

    def append(self, b):
        if not self.is_full() and b:
            super(SizedList, self).append(b)
            self.size += len(b)
            self.end_with_ascii = b[-1] <= 126

    def clean(self):
        self.size = 0
        del self[:]


class TtyIOParser:
    def __init__(self, width=80, height=24):
        self.screen = pyte.Screen(width, height)
        self.stream = pyte.ByteStream()
        self.stream.attach(self.screen)
        self.ps1_pattern = re.compile(r'^\[?.*@.*\]?[\$#]\s|mysql>\s')

    def clean_ps1_etc(self, command):
        return self.ps1_pattern.sub('', command)

    def is_prompt(self, data):
        # 判断是否为提示符 (PS1)
        return bool(self.ps1_pattern.search(data))

    def parse_output(self, data, sep='\n'):
        """
        Parse user command output

        :param data: output data list like, [b'data', b'data']
        :param sep:  line separator
        :return: output unicode data
        """
        output = []

        for d in data:
            self.stream.feed(d)
        try:
            for line in self.screen.display:
                if line.strip():
                    output.append(line)
        except IndexError:
            pass
        self.screen.reset()
        return sep.join(output[0:-1]).strip()

    def parse_input(self, data):
        """
        Parse user input command

        :param data: input data list, like [b'data', b'data']
        :return: command unicode
        """
        command = []
        for d in data:
            self.stream.feed(d)
        for line in self.screen.display:
            line = line.strip()
            if line:
                command.append(line)
        if command:
            command = command[-1]
        else:
            command = ''
        self.screen.reset()
        command = self.clean_ps1_etc(command)
        return command.strip()


class WrapperServer:
    """
    Base Server
    Achieve command record
    sub-class: Server, Telnet Server
    """

    def __init__(self, chan=None):
        self.chan = chan
        self._session_ref = None

        self._pre_input_state = True
        self._in_input_state = True
        self._input_initial = False

        self._enter_vim_mark = b'\x1b[?25l\x1b[37;1H\x1b[1m'
        self._exit_vim_mark = b'\x1b[37;1H\x1b[K\x1b'
        self._in_vim_state = False

        self.input_data = SizedList(maxsize=1024)
        self.output_data = SizedList(maxsize=1024)
        self._input = ""
        self._output = ""

        self._cmd_parser = TtyIOParser()

    def s_input_state_filter(self, data):
        self._pre_input_state = self._in_input_state
        if self._in_vim_state:
            self._in_input_state = False
        # 输入了回车键
        elif self._have_enter_char(data):
            self._in_input_state = False
        else:
            self._in_input_state = True
        return data

    def s_parse_input_output_filter(self, data):
        # 输入了回车键, 计算输入的命令
        if not self._in_input_state:
            self._input = self._parse_input()
        # 用户输入了内容，但是上次没在输入状态，也就是用户刚开始输入了，结算上次输出内容

        if not self._pre_input_state and self._in_input_state:
            self._output = self._parse_output()
            print("\n{}\nInput: {}\nOutput: {}\n{}".format(
                "#" * 30 + " Command " + "#" * 30,
                self._input, self._output,
                "#" * 30 + " End " + "#" * 30,
            ))
            self.input_data.clean()
            self.output_data.clean()
        return data

    def r_input_output_data_filter(self, data):
        if not self._input_initial:
            return data
        if self._in_input_state:
            self.input_data.append(data)
        else:
            self.output_data.append(data)
        return data

    def send(self, data):
        # self.s_initial_filter(data)
        self.s_input_state_filter(data)
        try:
            self.s_parse_input_output_filter(data)
        except Exception as e:
            logger.error(e, exc_info=True)
        return self.chan.send(data)

    def recv(self, size):
        data = self.chan.recv(size)
        self.r_input_output_data_filter(data)
        return data

    @staticmethod
    def _have_enter_char(s):
        for c in ENTER_CHAR:
            if c in s:
                return True
        return False

    def _parse_output(self):
        if not self.output_data:
            return ''
        return self._cmd_parser.parse_output(self.output_data)

    def _parse_input(self):
        if not self.input_data:
            return
        return self._cmd_parser.parse_input(self.input_data)

    def fileno(self):
        return self.chan.fileno()

    def close(self):
        logger.info("Close server to {}".format(self))
        self.s_input_state_filter(b'')
        self.s_parse_input_output_filter(b'')
        self.chan.close()

    def __getattr__(self, item):
        return getattr(self.chan, item)

    def __str__(self):
        return "<To: {}>".format(str(self.asset))



