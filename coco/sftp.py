import os
import tempfile
import paramiko
import time
from datetime import datetime

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
        for s in self.get_asset_system_users(host):
            if s.name == su:
                system_user = s
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

    def su_in_asset(self, su, host):
        system_users = self.get_asset_system_users(host)
        if su in [s.name for s in system_users]:
            return True
        else:
            return False

    def create_ftp_log(self, path, operate, is_success=True, filename=None):
        host, su, rpath = self.parse_path(path)
        date_start = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " +0000",
        data = {
            "user": self.server.request.user.username,
            "asset": host,
            "system_user": su,
            "remote_addr": self.server.request.addr[0],
            "operate": operate,
            "filename": filename or rpath,
            "date_start": date_start,
            "is_success": is_success,
        }
        for i in range(1, 4):
            ok = self.server.app.service.create_ftp_log(data)
            if ok:
                break
            else:
                time.sleep(0.5)
                continue

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

        e = OSError("Not that dir")
        if host and host not in self.hosts:
            return paramiko.SFTPServer.convert_errno(e.errno)
        if su and not self.su_in_asset(su, host):
            return paramiko.SFTPServer.convert_errno(e.errno)

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
        success = False

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
        if 'r' in mode:
            operate = "Download"
        else:
            operate = "Upload"

        result = None
        if sftp is not None:
            try:
                f = sftp.open(rpath, mode, bufsize=4096)
                obj = paramiko.SFTPHandle(flags)
                obj.filename = rpath
                obj.readfile = f
                obj.writefile = f
                result = obj
                success = True
            except OSError:
                pass
        self.create_ftp_log(path, operate, success)
        return result

    def remove(self, path):
        sftp, rpath = self.get_sftp_rpath(path)
        success = False

        if sftp is not None:
            try:
                sftp.remove(rpath)
            except OSError as e:
                result = paramiko.SFTPServer.convert_errno(e.errno)
            else:
                result = paramiko.SFTP_OK
                success = True
        else:
            result = paramiko.SFTP_FAILURE
        self.create_ftp_log(path, "Delete", success)
        return result

    def rename(self, src, dest):
        host1, su1, rsrc = self.parse_path(src)
        host2, su2, rdest = self.parse_path(dest)
        success = False

        if host1 == host2 and su1 == su2 and host1:
            sftp = self.get_host_sftp(host1, su1)
            try:
                sftp.rename(rsrc, rdest)
                success = True
            except OSError as e:
                result = paramiko.SFTPServer.convert_errno(e.errno)
            else:
                result = paramiko.SFTP_OK
        else:
            result = paramiko.SFTP_FAILURE
        filename = "{}=>{}".format(rsrc, rdest)
        self.create_ftp_log(rsrc, "Rename", success, filename=filename)
        return result

    def mkdir(self, path, attr):
        sftp, rpath = self.get_sftp_rpath(path)
        success = False

        if sftp is not None and rpath != '/':
            try:
                sftp.mkdir(rpath)
                success = True
            except OSError as e:
                result = paramiko.SFTPServer.convert_errno(e.errno)
            else:
                result = paramiko.SFTP_OK
        else:
            result = paramiko.SFTP_FAILURE
        self.create_ftp_log(path, "Mkdir", success)
        return result

    def rmdir(self, path):
        sftp, rpath = self.get_sftp_rpath(path)
        success = False

        if sftp is not None:
            try:
                sftp.rmdir(rpath)
                success = True
            except OSError as e:
                result = paramiko.SFTPServer.convert_errno(e.errno)
            else:
                result = paramiko.SFTP_OK
        else:
            result = paramiko.SFTP_FAILURE
        self.create_ftp_log(path, "Rmdir", success)
        return result

    # def chattr(self, path, attr):
    #     sftp, rpath = self.get_sftp_rpath(path)
    #     if sftp is not None:
    #         if attr._flags & attr.FLAG_PERMISSIONS:
    #             sftp.chmod(rpath, attr.st_mode)
    #         if attr._flags & attr.FLAG_UIDGID:
    #             sftp.chown(rpath, attr.st_uid, attr.st_gid)
    #         if attr._flags & attr.FLAG_AMTIME:
    #             sftp.utime(rpath, (attr.st_atime, attr.st_mtime))
    #         if attr._flags & attr.FLAG_SIZE:
    #             sftp.truncate(rpath, attr.st_size)
    #         return paramiko.SFTP_OK
