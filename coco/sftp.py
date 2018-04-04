# Copyright (C) 2003-2009  Robey Pointer <robeypointer@gmail.com>
#
# This file is part of paramiko.
#
# Paramiko is free software; you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# Paramiko is distrubuted in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Paramiko; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA.

"""
A stub SFTP server for loopback SFTP testing.
"""

import os
import tempfile
import time
import socket
import argparse
import sys
import textwrap
import paramiko

paramiko.util.log_to_file('/tmp/ftpserver.log', 'DEBUG')


class StubServer(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        # all are allowed
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        # all are allowed
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def get_allowed_auths(self, username):
        """List availble auth mechanisms."""
        return "password,publickey"


class StubSFTPServer(paramiko.SFTPServerInterface):
    hosts = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_perm_hosts()
        self._sftp = {}

    def get_host_sftp(self, host):
        if host not in self._sftp:
            t = paramiko.Transport(('192.168.244.176', 22))
            t.connect(username='root', password='redhat123')
            sftp = paramiko.SFTPClient.from_transport(t)
            self._sftp[host] = sftp
            return sftp
        else:
            return self._sftp[host]

    def get_perm_hosts(self):
        self.hosts = ['centos', 'localhost']

    @staticmethod
    def parse_path(path):
        host, *rpath = path.lstrip('/').split('/')
        rpath = '/' + '/'.join(rpath)
        return host, rpath

    def get_sftp_rpath(self, path):
        host, rpath = self.parse_path(path)
        sftp = self.get_host_sftp(host) if host else None
        return sftp, rpath

    @staticmethod
    def stat_host_dir():
        tmp = tempfile.TemporaryDirectory()
        attr = paramiko.SFTPAttributes.from_stat(os.stat(tmp.name))
        tmp.cleanup()
        return attr

    def list_folder(self, path):
        output = []
        if path == "/":
            for filename in self.hosts:
                attr = self.stat_host_dir()
                attr.filename = filename
                output.append(attr)
        else:
            sftp, rpath = self.get_sftp_rpath(path)
            file_list = sftp.listdir(rpath)
            for filename in file_list:
                attr = sftp.stat(os.path.join(rpath, filename))
                attr.filename = filename
                output.append(attr)
        return output

    def stat(self, path):
        host, rpath = self.parse_path(path)
        if host and not rpath:
            attr = self.stat_host_dir()
            attr.filename = host
            return attr
        else:
            sftp = self.get_host_sftp(host)
            return sftp.stat(rpath)

    def lstat(self, path):
        host, rpath = self.parse_path(path)

        if host == '':
            attr = self.stat_host_dir()
            attr.filename = host
        else:
            sftp = self.get_host_sftp(host)
            attr = sftp.stat(rpath)
            attr.filename = os.path.basename(path)
        return attr

    def open(self, path, flags, attr):
        binary_flag = getattr(os, 'O_BINARY', 0)
        flags |= binary_flag

        if flags & os.O_WRONLY:
            if flags & os.O_APPEND:
                mode = 'ab'
            else:
                mode = 'wb'
        elif flags & os.O_RDWR:
            if flags & os.O_APPEND:
                mode = 'a+b'
            else:
                mode = 'r+b'
        else:
            mode = 'rb'

        sftp, rpath = self.get_sftp_rpath(path)
        if sftp is not None:
            f = sftp.open(rpath, mode, bufsize=4096)
            obj = paramiko.SFTPHandle(flags)
            obj.filename = rpath
            obj.readfile = f
            obj.writefile = f
            return obj

    def remove(self, path):
        sftp, rpath = self.get_sftp_rpath(path)

        if sftp is not None:
            try:
                sftp.remove(rpath)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK
        else:
            return paramiko.SFTP_FAILURE

    def rename(self, src, dest):
        host1, rsrc = self.parse_path(src)
        host2, rdest = self.parse_path(dest)

        if host1 == host2 and host1:
            sftp = self.get_host_sftp(host2)
            try:
                sftp.rename(rsrc, rdest)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK
        return paramiko.SFTP_FAILURE

    def mkdir(self, path, attr):
        sftp, rpath = self.get_sftp_rpath(path)
        if sftp is not None:
            try:
                sftp.mkdir(rpath)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK
        return paramiko.SFTP_FAILURE

    def rmdir(self, path):
        print("Call {}".format("Rmdir"))
        sftp, rpath = self.get_sftp_rpath(path)
        if sftp is not None:
            try:
                sftp.rmdir(rpath)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

    def chattr(self, path, attr):
        print("Call {}".format("Chattr"))
        sftp, rpath = self.get_sftp_rpath(path)
        if sftp is not None:
            if attr._flags & attr.FLAG_PERMISSIONS:
                sftp.chmod(rpath, attr.st_mode)
            if attr._flags & attr.FLAG_UIDGID:
                sftp.chown(rpath, attr.st_uid, attr.st_gid)
            if attr._flags & attr.FLAG_AMTIME:
                sftp.utime(rpath, (attr.st_atime, attr.st_mtime))
            if attr._flags & attr.FLAG_SIZE:
                sftp.truncate(rpath, attr.st_size)
            return paramiko.SFTP_OK


HOST, PORT = 'localhost', 3373
BACKLOG = 10


def start_server(host, port, keyfile, level):
    paramiko_level = getattr(paramiko.common, level)
    paramiko.common.logging.basicConfig(level=paramiko_level)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    server_socket.bind((host, port))
    server_socket.listen(BACKLOG)

    while True:
        conn, addr = server_socket.accept()

        host_key = paramiko.RSAKey.from_private_key_file(keyfile)
        transport = paramiko.Transport(conn)
        transport.add_server_key(host_key)
        transport.set_subsystem_handler(
            'sftp', paramiko.SFTPServer, StubSFTPServer)

        server = StubServer()
        transport.start_server(server=server)

        channel = transport.accept()
        while transport.is_active():
            time.sleep(1)


def main():
    usage = """\
    usage: sftpserver [options]
    -k/--keyfile should be specified
    """
    parser = argparse.ArgumentParser(usage=textwrap.dedent(usage))
    parser.add_argument(
        '--host', dest='host', default=HOST,
        help='listen on HOST [default: %(default)s]'
    )
    parser.add_argument(
        '-p', '--port', dest='port', type=int, default=PORT,
        help='listen on PORT [default: %(default)d]'
    )
    parser.add_argument(
        '-l', '--level', dest='level', default='INFO',
        help='Debug level: WARNING, INFO, DEBUG [default: %(default)s]'
    )
    parser.add_argument(
        '-k', '--keyfile', dest='keyfile', metavar='FILE',
        help='Path to private key, for example /tmp/test_rsa.key'
    )

    args = parser.parse_args()

    if args.keyfile is None:
        parser.print_help()
        sys.exit(-1)

    start_server(args.host, args.port, args.keyfile, args.level)


if __name__ == '__main__':
    main()