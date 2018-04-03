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
from paramiko import ServerInterface, SFTPServerInterface, SFTPServer, \
    SFTPAttributes, SFTPHandle, SFTP_OK, AUTH_SUCCESSFUL, OPEN_SUCCEEDED, \
    SFTPClient
import time
import socket
import argparse
import sys
import textwrap

import paramiko

sftp_client = None
# paramiko.util.log_to_file('/tmp/ftpserver.log')


class StubServer(ServerInterface):
    def check_auth_password(self, username, password):
        # all are allowed
        return AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        # all are allowed
        return AUTH_SUCCESSFUL

    def check_channel_request(self, kind, chanid):
        return OPEN_SUCCEEDED

    def get_allowed_auths(self, username):
        """List availble auth mechanisms."""
        return "password,publickey"


class StubSFTPHandle(SFTPHandle):
    def stat(self):
        print("Call handle stat")
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def chattr(self, attr):
        # python doesn't have equivalents to fchown or fchmod, so we have to
        # use the stored filename
        try:
            SFTPServer.set_file_attr(self.filename, attr)
            return SFTP_OK
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)


class StubSFTPServer(SFTPServerInterface):
    # assume current folder is a fine root
    # (the tests always create and eventualy delete a subfolder, so there shouldn't be any mess)

    ROOT = os.getcwd()
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

    @staticmethod
    def stat_host_dir():
        tmp = tempfile.TemporaryDirectory()
        d = tmp.name
        attr = SFTPAttributes.from_stat(
            os.stat(d)
        )
        tmp.cleanup()
        return attr

    def list_folder(self, path):
        print("Call list folder: {}".format(path))
        host, rpath = self.parse_path(path)
        output = []

        if host == '':
            for filename in self.hosts:
                attr = self.stat_host_dir()
                attr.filename = filename
                output.append(attr)
        else:
            sftp = self.get_host_sftp(host)
            file_list = sftp.listdir(rpath)
            for filename in file_list:
                attr = sftp.stat(os.path.join(rpath, filename))
                attr.filename = filename
                output.append(attr)
        return output

    def stat(self, path):
        host, *rpath = path.lstrip('/').split('/')
        rpath = '/' + '/'.join(rpath)

        if host == '':
            attr = self.stat_host_dir()
            attr.filename = host
            return attr
        else:
            sftp = self.get_host_sftp(host)
            return sftp.stat(rpath)

    def lstat(self, path):
        print("Call lstat: {}".format(path))
        host, *rpath = path.lstrip('/').split('/')
        rpath = '/' + '/'.join(rpath)

        if host == '':
            attr = self.stat_host_dir()
            attr.filename = host
        else:
            sftp = self.get_host_sftp(host)
            attr = sftp.stat(rpath)
            attr.filename = os.path.basename(path)
        return attr

    def open(self, path, flags, attr):
        print("Call {}: {}**{}**{}".format("Open", path, flags, attr))
        host, *rpath = path.lstrip('/').split('/')
        rpath = '/' + '/'.join(rpath)

        binary_flag = getattr(os, 'O_BINARY', 0)
        flags |= binary_flag

        if (flags & os.O_CREAT) and (attr is not None):
            attr._flags &= ~attr.FLAG_PERMISSIONS
            SFTPServer.set_file_attr(path, attr)
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

        if host != "":
            sftp = self.get_host_sftp(host)
            f = sftp.open(rpath, mode, bufsize=1024)
            obj = StubSFTPHandle(flags)
            obj.filename = path
            obj.readfile = f
            obj.writefile = f
            return obj

    def remove(self, path):
        print("Call {}".format("Remove"))
        path = self._realpath(path)
        try:
            os.remove(path)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def rename(self, oldpath, newpath):
        print("Call {}".format("Rename"))
        oldpath = self._realpath(oldpath)
        newpath = self._realpath(newpath)
        try:
            os.rename(oldpath, newpath)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def mkdir(self, path, attr):
        print("Call {}".format("Mkdir"))
        path = self._realpath(path)
        try:
            os.mkdir(path)
            if attr is not None:
                SFTPServer.set_file_attr(path, attr)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def rmdir(self, path):
        print("Call {}".format("Rmdir"))
        path = self._realpath(path)
        try:
            os.rmdir(path)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def chattr(self, path, attr):
        print("Call {}".format("Chattr"))
        path = self._realpath(path)
        try:
            SFTPServer.set_file_attr(path, attr)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def symlink(self, target_path, path):
        print("Call {}".format("Symlink"))
        path = self._realpath(path)
        if (len(target_path) > 0) and (target_path[0] == '/'):
            # absolute symlink
            target_path = os.path.join(self.ROOT, target_path[1:])
            if target_path[:2] == '//':
                # bug in os.path.join
                target_path = target_path[1:]
        else:
            # compute relative to path
            abspath = os.path.join(os.path.dirname(path), target_path)
            if abspath[:len(self.ROOT)] != self.ROOT:
                # this symlink isn't going to work anyway -- just break it immediately
                target_path = '<error>'
        try:
            os.symlink(target_path, path)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def readlink(self, path):
        print("Call {}".format("Read link"))
        path = self._realpath(path)
        try:
            symlink = os.readlink(path)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        # if it's absolute, remove the root
        if os.path.isabs(symlink):
            if symlink[:len(self.ROOT)] == self.ROOT:
                symlink = symlink[len(self.ROOT):]
                if (len(symlink) == 0) or (symlink[0] != '/'):
                    symlink = '/' + symlink
            else:
                symlink = '<error>'
        return symlink


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