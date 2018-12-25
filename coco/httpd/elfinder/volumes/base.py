# -*- coding: utf-8 -*-
#
import base64
import os
import hashlib
import logging

logger = logging.getLogger(__name__)


class BaseVolume:
    def __init__(self, *args, **kwargs):
        self.base_path = '/'
        self.path_sep = '/'
        self.dir_mode = '0o755'
        self.file_mode = '0o644'
    #
    # @classmethod
    # def get_volume(cls, request):
    #     raise NotImplementedError

    def close(self):
        pass

    def get_volume_id(self):
        """ Returns the volume ID for the volume, which is used as a prefix
            for client hashes.
        """
        raise NotImplementedError

    def _remote_path(self, path):
        path = path.lstrip(self.path_sep)
        return self._join(self.base_path, path)

    def _path(self, _hash):
        """
        通过_hash获取path
        :param _hash:
        :return:
        """
        if _hash in ['', '/']:
            return self.path_sep
        volume_id, path = self._get_volume_id_and_path_from_hash(_hash)
        if volume_id != self.get_volume_id():
            return self.path_sep
        return path

    def _remote_path_h(self, _hash):
        path = self._path(_hash)
        return self._remote_path(path)

    def _is_root(self, path):
        return path == self.path_sep

    def _hash(self, path):
        """
        通过path生成hash
        :param path:
        :return:
        """
        if not self._is_root(path):
            path = path.rstrip(self.path_sep)
        _hash = "{}_{}".format(
            self.get_volume_id(),
            self._encode(path)
        )
        return _hash

    @staticmethod
    def _digest(s):
        m = hashlib.md5()
        m.update(s.encode())
        return str(m.hexdigest())

    @classmethod
    def _get_volume_id_and_path_from_hash(cls, _hash):
        volume_id, _path = _hash.split('_', 1)
        return volume_id, cls._decode(_path)

    def _encode(self, path):
        if not self._is_root(path):
            path = path.lstrip('/')
        if isinstance(path, str):
            path = path.encode()
        _hash = base64.b64encode(path).decode()
        _hash = _hash.translate(str.maketrans('+/=', '-_.')).rstrip('.')
        return _hash

    @staticmethod
    def _decode(_hash):
        _hash = _hash.translate(str.maketrans('-_.', '+/='))
        _hash += "=" * ((4 - len(_hash) % 4) % 4)
        if isinstance(_hash, str):
            _hash = _hash.encode()
        _hash = base64.b64decode(_hash).decode()
        return _hash

    @staticmethod
    def _base_name(path):
        return os.path.basename(path)

    def _dir_name(self, path):
        if path in ['', '/']:
            return self.path_sep
        path = path.rstrip('/')
        parent_path = os.path.dirname(path)
        return parent_path

    @staticmethod
    def _join(*args):
        return os.path.join(*args)

    def read_file_view(self, request, target):
        """ Django view function, used to display files in response to the
            'file' command.

            :param request: The original HTTP request.
            :param target: The hash of the target file.
            :returns: dict -- a dict describing the new directory.
        """
        raise NotImplementedError

    def info(self, target):
        """ Returns a dict containing information about the target directory
            or file. This data is used in response to 'open' commands to
            populates the 'cwd' response var.

            :param target: The hash of the directory for which we want info.
            If this is '', return information about the root directory.
            :returns: dict -- A dict describing the directory.
        """
        raise NotImplementedError

    def mkdir(self, name, parent):
        """ Creates a directory.

            :param name: The name of the new directory.
            :param parent: The hash of the parent directory.
            :returns: dict -- a dict describing the new directory.
        """
        raise NotImplementedError

    def mkfile(self, name, parent):
        """ Creates a directory.

            :param name: The name of the new file.
            :param parent: The hash of the parent directory.
            :returns: dict -- a dict describing the new file.
        """
        raise NotImplementedError

    def rename(self, name, target):
        """ Renames a file or directory.

            :param name: The new name of the file/directory.
            :param target: The hash of the target file/directory.
            :returns: dict -- a dict describing which objects were added and
            removed.
        """
        raise NotImplementedError

    def list(self, target, name_only=False):
        """ Lists the contents of a directory.

            :param target: The hash of the target directory.
            :param name_only: Only return the name
            :returns: list -- a list containing the names of files/directories
            in this directory.
        """
        raise NotImplementedError

    def tree(self, target):
        """ Get the sub directory of directory

        :param target: The hash of the target directory.
        :return: list - a list of containing the names of sub directories
        """
        raise NotImplementedError

    def parents(self, target, deep=0):
        """ Returns all parent folders and its sub directory on required deep
            This command is invoked when a directory is reloaded in the client.
            Data provided by 'parents' command should enable the correct drawing
            of tree hierarchy directories.
        :param target: The hash of the target directory.
        :param deep: The deep to show
        :return list - a list of containing parent and sub directory info
        """
        raise NotImplementedError

    def paste(self, targets, dest, cut):
        """ Moves/copies target files/directories from source to dest.

            If a file with the same name already exists in the dest directory
            it should be overwritten (the client asks the user to confirm this
            before sending the request).

            :param targets: A list of hashes of files/dirs to move/copy.
            :param dest: The new parent of the targets.
            :param cut: Boolean. If true, move the targets. If false, copy the
            targets.
            :returns: dict -- a dict describing which targets were moved/copied.
        """
        raise Exception("Not support paste")

    def remove(self, targets):
        """ Deletes the target files/directories.

            The 'rm' command takes a list of targets - this function is called
            for each target, so should only delete one file/directory.

            :param targets: A list of hashes of files/dirs to delete.
            :returns: string -- the hash of the file/dir that was deleted.
        """
        raise NotImplementedError

    def upload(self, files, parent):
        """ Uploads one or more files in to the parent directory.

            :param files: A list of uploaded file objects, as described here:
            https://docs.djangoproject.com/en/dev/topics/http/file-uploads/
            :param parent: The hash of the directory in which to create the
            new files.
            :returns: TODO
        """
        raise NotImplementedError

    def upload_as_chunk(self, files, chunk_name, parent):
        """
        Upload a large file as chunk
        :param files:
        :param chunk_name:
        :param cid:
        :param parent:
        :return:
        """
