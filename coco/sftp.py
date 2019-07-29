import os
import stat
import paramiko
import time
from datetime import datetime
from functools import wraps

from paramiko.sftp import SFTP_PERMISSION_DENIED, SFTP_NO_SUCH_FILE, \
    SFTP_FAILURE, SFTP_EOF, SFTP_CONNECTION_LOST

from coco.utils import get_logger
from .conf import config
from .service import app_service
from .connection import SSHConnection
from .interactive import InteractiveServer
from .const import (
    PERMS_ACTION_NAME_DOWNLOAD_FILE, PERMS_ACTION_NAME_UPLOAD_FILE,
    MANUAL_LOGIN,
)

CURRENT_DIR = os.path.dirname(__file__)
logger = get_logger(__file__)


def convert_error(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        error = None
        try:
            response = func(*args, **kwargs)
        except FileNotFoundError as e:
            error = e
            response = SFTP_NO_SUCH_FILE
        except PermissionError as e:
            error = e
            response = SFTP_PERMISSION_DENIED
        except OSError as e:
            error = e
            response = SFTP_CONNECTION_LOST
        except EOFError as e:
            error = e
            response = SFTP_EOF
        except Exception as e:
            logger.error(e, exc_info=True)
            error = e
            response = SFTP_FAILURE
        finally:
            if isinstance(error, Exception):
                logger.error(error)
        return response

    return wrapper


class SFTPServer(paramiko.SFTPServerInterface):
    # Home or /tmp or other path, must exist on all server
    root = config.SFTP_ROOT

    def __init__(self, server, **kwargs):
        """

        :param server: SSH Interface instance
        :param kwargs:

        hosts = {
            "hostname[.org]": {
                "asset": asset_instance,
                "system_users": {
                    system_user_name: system_user_instance,
                }
            }

        """
        super(SFTPServer, self).__init__(server, **kwargs)
        self.server = server
        self._sftp = {}
        self.hosts = self.get_permed_hosts()
        self.is_finished = False
        self.force_rm_folder = True if config.get("FORCE_REMOVE_FOLDER") else False

    def get_user_assets(self):
        user_id = self.server.connection.user.id
        assets = InteractiveServer._user_assets_cached.get(user_id)
        if assets is None:
            assets, new_etag = app_service.get_user_assets(
                self.server.connection.user, cache_policy='1'
            )
        return assets

    def get_permed_hosts(self):
        hosts = {}
        assets = self.get_user_assets()
        for asset in assets:
            if not asset.has_protocol('ssh'):
                continue
            value = {}
            key = asset.hostname
            if asset.org_id:
                key = "{}.{}".format(asset.hostname, asset.org_name)
            value['asset'] = asset
            value['system_users'] = {
                su.name: su
                for su in asset.system_users_granted
            }
            hosts[key] = value
        return hosts

    def session_ended(self):
        self.is_finished = True
        super(SFTPServer, self).session_ended()
        for _, v in self._sftp.items():
            sftp = v['client']
            conn = v.get('connection')
            sftp.close()
            conn.close()
        self._sftp = {}

    def get_host_sftp(self, host, su):
        asset = self.hosts.get(host, {}).get('asset')
        system_user = self.get_host_system_users(host, only_name=False).get(su)

        if not asset or not system_user:
            raise PermissionError("No asset or system user explicit")

        cache_key = '{}@{}'.format(su, host)
        if cache_key in self._sftp:
            return self._sftp[cache_key]

        conn = SSHConnection.new_connection(self.server.connection.user,
                                            asset, system_user)
        __sftp = conn.get_sftp()
        if __sftp:
            sftp = {
                'client': __sftp, 'connection': conn,
                'home': __sftp.normalize('')
            }
            self._sftp[cache_key] = sftp
            return sftp
        elif system_user.login_mode == MANUAL_LOGIN:
            raise PermissionError(
                "System user is in manual login mode, "
                "please use SSH protocol to connect assets first."
            )
        else:
            raise OSError("Can not connect asset sftp server: {}".format(conn.error))

    def host_has_unique_su(self, host):
        host_sus = self.get_host_system_users(host, only_name=True)
        logger.debug("Host system users: {}".format(host_sus))
        unique = False
        su = ''
        if len(host_sus) == 1:
            unique = True
            su = host_sus[0]
        return unique, su

    def parse_path(self, path):
        data = path.lstrip('/').split('/')
        request = {"host": "", "su": "", "dpath": "", "su_unique": False}

        if len(data) == 1 and not data[0]:
            return request

        host, path = data[0], data[1:]
        request["host"] = host
        unique, su = self.host_has_unique_su(host)
        if unique:
            request['su'] = su
            request['su_unique'] = True
        else:
            request['su'], path = (path[0], path[1:]) if path else ('', path)
        request['dpath'] = '/'.join(path)
        return request

    def get_sftp_client_rpath(self, request):
        if isinstance(request, str):
            request = self.parse_path(request)
        host, su, dpath = request['host'], request['su'], request['dpath']
        if host and su:
            sftp = self.get_host_sftp(host, su)
            if self.root.lower() in ['~', 'home']:
                root = sftp['home']
            else:
                root = self.root
            rpath = os.path.join(root, dpath.lstrip('/'))
            return sftp['client'], rpath
        else:
            raise FileNotFoundError()

    def is_su_in_asset(self, su, host):
        system_users = self.get_host_system_users(host, only_name=True)
        if su in system_users:
            return True
        else:
            return False

    def create_ftp_log(self, path, operate, is_success=True, filename=None):
        request = self.parse_path(path)
        host, su = request['host'], request['su']
        c, rpath = self.get_sftp_client_rpath(request)
        asset = self.hosts.get(host)['asset']
        date_start = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " +0000",
        data = {
            "user": "{} ({})".format(self.server.connection.user.name,
                                     self.server.connection.user.username),
            "asset": host,
            "org_id": asset.org_id,
            "system_user": su,
            "remote_addr": self.server.connection.addr[0],
            "operate": operate,
            "filename": filename or rpath,
            "date_start": date_start,
            "is_success": is_success,
        }
        for i in range(1, 4):
            ok = app_service.create_ftp_log(data)
            if ok:
                break
            else:
                time.sleep(0.5)
                continue

    @staticmethod
    def stat_fake_dir():
        s = os.stat(CURRENT_DIR)
        attr = paramiko.SFTPAttributes.from_stat(s)
        return attr

    def get_host_system_users(self, host, only_name=False):
        system_users = self.hosts.get(host, {}).get('system_users', {})
        if only_name:
            system_users = list(system_users.keys())
        return system_users

    @convert_error
    def list_folder(self, path):
        output = []
        request = self.parse_path(path)
        logger.debug("List folder: {} => {}".format(path, request))
        if not request['host']:  # It's root
            for hostname in self.hosts:
                attr = self.stat_fake_dir()
                attr.filename = hostname
                output.append(attr)
        elif not request['su']:
            for su in self.get_host_system_users(request['host']):
                attr = self.stat_fake_dir()
                attr.filename = su
                output.append(attr)
        else:
            client, rpath = self.get_sftp_client_rpath(request)
            output = client.listdir_attr(rpath)
            show_hidden_file = config['SFTP_SHOW_HIDDEN_FILE']
            if not show_hidden_file:
                output = [attr for attr in output if not attr.filename.startswith('.')]
        return output

    @convert_error
    def stat(self, path):
        request = self.parse_path(path)
        host, su, dpath, unique = request['host'], request['su'], \
                                  request['dpath'], request['su_unique']

        logger.debug("Stat path: {} => {}".format(path, request))
        if not host or not su:
            stat = self.stat_fake_dir()
            stat.filename = host or su or '/'
            return stat

        if host and host not in self.hosts:
            raise PermissionError("Permission deny")
        if su and not self.is_su_in_asset(su, host):
            raise PermissionError("Permission deny")

        client, rpath = self.get_sftp_client_rpath(request)
        logger.debug("Stat path2: {} => {}".format(client, rpath))
        stat = client.stat(rpath)
        return stat

    @convert_error
    def lstat(self, path):
        return self.stat(path)

    @staticmethod
    def validate_permission(system_user, action):
        check_actions = [action]
        granted_actions = getattr(system_user, 'actions', [])
        actions = list(set(granted_actions).intersection(set(check_actions)))
        return bool(actions)

    def check_action(self, path, action):
        request = self.parse_path(path)
        host, su = request['host'], request['su']
        system_user = self.hosts.get(host, {}).get('system_users', {}).get(su)
        if not system_user:
            raise PermissionError("No system user explicit")

        if not self.validate_permission(system_user, action):
            raise PermissionError("Permission deny")

    @convert_error
    def open(self, path, flags, attr=None):
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

        if 'r' in mode:
            operate = "Download"
            action = PERMS_ACTION_NAME_DOWNLOAD_FILE
        elif 'a' in mode:
            operate = "Append"
            action = PERMS_ACTION_NAME_UPLOAD_FILE
        else:
            operate = "Upload"
            action = PERMS_ACTION_NAME_UPLOAD_FILE

        success = False
        try:
            self.check_action(path, action)
            client, rpath = self.get_sftp_client_rpath(path)
            f = client.open(rpath, mode, bufsize=4096)
            f.prefetch()
            obj = paramiko.SFTPHandle(flags)
            obj.filename = rpath
            obj.readfile = f
            obj.writefile = f
            result = obj
            success = True
            return result
        finally:
            self.create_ftp_log(path, operate, success)

    @convert_error
    def remove(self, path):
        self.check_action(path, action=PERMS_ACTION_NAME_UPLOAD_FILE)
        client, rpath = self.get_sftp_client_rpath(path)
        success = False

        try:
            client.remove(rpath)
            success = True
            return paramiko.SFTP_OK
        finally:
            self.create_ftp_log(path, "Delete", success)

    @convert_error
    def rename(self, src, dest):
        self.check_action(src, action=PERMS_ACTION_NAME_UPLOAD_FILE)
        client, rsrc = self.get_sftp_client_rpath(src)
        client2, rdest = self.get_sftp_client_rpath(dest)
        success = False
        filename = "{}=>{}".format(rsrc, rdest)

        try:
            if client == client2:
                client.rename(rsrc, rdest)
                success = True
                return paramiko.SFTP_OK
            else:
                raise FileNotFoundError("Can't rename {} => {}".format(src, dest))
        finally:
            self.create_ftp_log(src, "Rename", success, filename=filename)

    @convert_error
    def mkdir(self, path, attr=0o755):
        self.check_action(path, action=PERMS_ACTION_NAME_UPLOAD_FILE)
        client, rpath = self.get_sftp_client_rpath(path)
        success = False

        try:
            if rpath == '/':
                raise PermissionError("Create '/', are you sure?")
            client.mkdir(rpath)
            success = True
            return paramiko.SFTP_OK
        finally:
            self.create_ftp_log(path, "Mkdir", success)

    @convert_error
    def rmdir(self, path):
        self.check_action(path, action=PERMS_ACTION_NAME_UPLOAD_FILE)
        client, rpath = self.get_sftp_client_rpath(path)
        success = False

        try:
            if self.force_rm_folder:
                self._rmdir(client, rpath)
            else:
                client.rmdir(rpath)
            success = True
            return paramiko.SFTP_OK
        finally:
            self.create_ftp_log(path, "Rmdir", success)

    def _rmdir(self, sftp_client, path):
        for item in list(sftp_client.listdir_iter(path)):
            filepath = "/".join([path, item.filename])
            if stat.S_IFMT(item.st_mode) == stat.S_IFDIR:
                self._rmdir(sftp_client, filepath)
                continue
            sftp_client.remove(filepath)
        sftp_client.rmdir(path)


class FakeServer:
    pass


class FakeTransport:
    _trans = None

    @staticmethod
    def getpeername():
        return '127.0.0.1', config['SSHD_PORT']

    @staticmethod
    def get_username():
        return 'fake'


class FakeChannel:
    _chan = None

    def get_transport(self):
        return FakeTransport()

    @classmethod
    def new(cls):
        if not cls._chan:
            cls._chan = cls()
        return cls._chan


class InternalSFTPClient(SFTPServer):
    def __init__(self, connection):
        fake_server = FakeServer()
        fake_server.connection = connection
        super(InternalSFTPClient, self).__init__(fake_server)

    def listdir_attr(self, path):
        return self.list_folder.__wrapped__(self, path)

    def open(self, path, mode, **kwargs):
        client, rpath = self.get_sftp_client_rpath(path)
        if 'r' in mode:
            operate = "Download"
            action = PERMS_ACTION_NAME_DOWNLOAD_FILE
        else:
            operate = "Upload"
            action = PERMS_ACTION_NAME_UPLOAD_FILE

        success = False
        try:
            self.check_action(path, action=action)
            f = client.open(rpath, mode, bufsize=4096)
            success = True
            return f
        finally:
            self.create_ftp_log(path, operate, success)

    def stat(self, path):
        attr = super(InternalSFTPClient, self).stat.__wrapped__(self, path)
        return attr

    def lstat(self, path):
        attr = super(InternalSFTPClient, self).lstat.__wrapped__(self, path)
        return attr

    def rename(self, src, dest):
        return super(InternalSFTPClient, self).rename.__wrapped__(self, src, dest)

    def mkdir(self, path, attr=0o755):
        return super(InternalSFTPClient, self).mkdir.__wrapped__(self, path, attr)

    def rmdir(self, path):
        return super(InternalSFTPClient, self).rmdir.__wrapped__(self, path)

    def get_channel(self):
        return FakeChannel.new()

    def unlink(self, path):
        return super(InternalSFTPClient, self).remove.__wrapped__(self, path)

    def putfo(self, f, path, callback=None, confirm=True):
        self.check_action(path, action=PERMS_ACTION_NAME_UPLOAD_FILE)
        client, rpath = self.get_sftp_client_rpath(path)
        success = False
        try:
            attr = client.putfo(f, rpath, callback=callback, confirm=confirm)
            success = True
            return attr
        finally:
            self.create_ftp_log(path, 'Upload', success)

    def close(self):
        return self.session_ended()
