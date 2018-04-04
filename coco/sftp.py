import os
import tempfile
import paramiko

from .connection import SSHConnection


class SFTPServer(paramiko.SFTPServerInterface):
    root = '/tmp'

    def __init__(self, server, **kwargs):
        super().__init__(server, **kwargs)
        self.server = server
        self._sftp = {}
        self.hosts = self.get_perm_hosts()

    def get_host_sftp(self, host, su):
        asset = self.hosts.get(host)
        system_user = None
        for system_user in self.get_asset_system_users(host):
            if system_user.name == su:
                break

        if not asset or not system_user:
            raise OSError("No asset or system user explicit")

        if host not in self._sftp:
            ssh = SSHConnection(self.server.app)
            sftp, msg = ssh.get_sftp(asset, system_user)
            if sftp:
                self._sftp[host] = sftp
                return sftp
            else:
                raise OSError("Can not connect asset sftp server")
        else:
            return self._sftp[host]

    def get_perm_hosts(self):
        assets = self.server.app.service.get_user_assets(
            self.server.request.user
        )
        return {asset.hostname: asset for asset in assets}

    def parse_path(self, path):
        data = path.lstrip('/').split('/')
        su = rpath = ''
        if len(data) == 1:
            host = data[0]
        elif len(data) == 2:
            host, su = data
            rpath = self.root
        else:
            host, su, *rpath = data
            rpath = os.path.join(self.root, '/'.join(rpath))
        return host, su, rpath

    def get_sftp_rpath(self, path):
        host, su, rpath = self.parse_path(path)
        sftp = self.get_host_sftp(host, su) if host and su else None
        return sftp, rpath

    def get_asset_system_users(self, host):
        asset = self.hosts.get(host)
        if not asset:
            return []
        return [su for su in asset.system_users_granted if su.protocol == "ssh"]

    @staticmethod
    def stat_host_dir():
        tmp = tempfile.TemporaryDirectory()
        attr = paramiko.SFTPAttributes.from_stat(os.stat(tmp.name))
        tmp.cleanup()
        return attr

    def list_folder(self, path):
        output = []
        host, su, rpath = self.parse_path(path)
        if not host:
            for hostname in self.hosts:
                attr = self.stat_host_dir()
                attr.filename = hostname
                output.append(attr)
        elif not su:
            for su in self.get_asset_system_users(host):
                attr = self.stat_host_dir()
                attr.filename = su.name
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
        host, su, rpath = self.parse_path(path)
        if not rpath or rpath == "/":
            attr = self.stat_host_dir()
            attr.filename = su or host
            return attr
        else:
            sftp = self.get_host_sftp(host, su)
            return sftp.stat(rpath)

    def lstat(self, path):
        host, su, rpath = self.parse_path(path)

        if not rpath or rpath == "/":
            attr = self.stat_host_dir()
            attr.filename = su or host
        else:
            sftp = self.get_host_sftp(host, su)
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
        host1, su1, rsrc = self.parse_path(src)
        host2, su2, rdest = self.parse_path(dest)

        if host1 == host2 and su1 == su2 and host1:
            sftp = self.get_host_sftp(host1, su1)
            try:
                sftp.rename(rsrc, rdest)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK
        return paramiko.SFTP_FAILURE

    def mkdir(self, path, attr):
        sftp, rpath = self.get_sftp_rpath(path)
        if sftp is not None and rpath != '/':
            try:
                sftp.mkdir(rpath)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK
        return paramiko.SFTP_FAILURE

    def rmdir(self, path):
        sftp, rpath = self.get_sftp_rpath(path)
        if sftp is not None:
            try:
                sftp.rmdir(rpath)
            except OSError as e:
                return paramiko.SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

    def chattr(self, path, attr):
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
