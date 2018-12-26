# -*- coding: utf-8 -*-
#
import stat
import threading

from flask import send_file
import requests

from coco.utils import get_logger
from .base import BaseVolume

logger = get_logger(__name__)


class SFTPVolume(BaseVolume):
    def __init__(self, sftp):
        self.sftp = sftp
        self.root_name = 'Home'
        self._stat_cache = {}
        self.lock = threading.Lock()
        super(SFTPVolume, self).__init__()

    def close(self):
        self.sftp.close()

    def get_volume_id(self):
        tran = self.sftp.get_channel().get_transport()
        addr = tran.getpeername()
        username = tran.get_username()
        volume_id = '{}@{}:{}'.format(username, *addr)
        return self._digest(volume_id)

    def info(self, target):
        """
        获取target的信息
        :param target:
        :return:
        """
        path = self._path(target)
        # print("Info target '{}' {}".format(target, path))
        return self._info(path)

    def _info(self, path, attr=None):
        remote_path = self._remote_path(path)
        # print('_Info: {} => {}'.format(path, remote_path))
        if attr is None:
            attr = self.sftp.lstat(remote_path)
        if not hasattr(attr, 'filename'):
            filename = self.root_name if self._is_root(path) else self._base_name(remote_path)
            attr.filename = filename

        parent_path = self._dir_name(path)
        data = {
            "name": attr.filename,
            "hash": self._hash(path),
            "phash": self._hash(parent_path),
            "ts": attr.st_mtime,
            "size": attr.st_size,
            "mime": "directory" if stat.S_ISDIR(attr.st_mode) else "file",
            "locked": 0,
            "hidden": 0,
            "read": 1,
            "write": 1,
        }
        if data["mime"] == 'directory':
            data["dirs"] = 1

        if self._is_root(path):
            data.pop('phash', None)
            data['name'] = self.root_name
            data['locked'] = 1
            data['volume_id'] = self.get_volume_id()
        return data

    def _list(self, path, name_only=False):
        """ Returns current dir dirs/files
        """
        remote_path = self._remote_path(path)
        # print("_list {} => {}".format(path, remote_path))
        if name_only:
            return self.sftp.listdir(remote_path)
        files = []
        children_attrs = self.sftp.listdir_attr(remote_path)
        for item in children_attrs:
            item_path = self._join(path, item.filename)
            info = self._info(item_path, attr=item)
            files.append(info)
        return files

    def list(self, target, name_only=False):
        """ Returns a list of files/directories in the target directory. """
        path = self._path(target)
        with self.lock:
            return self._list(path)

    def tree(self, target):
        """ Get the sub directory of directory
        """
        path = self._path(target)
        with self.lock:
            infos = self._list(path)
            tree = list(filter(lambda x: x['mime'] == 'directory', infos))
            return tree

    def parents(self, target, depth=0):
        """
        获取目录的父目录, 如果deep为0，则直到根
        """
        path = self._path(target).rstrip(self.path_sep)
        with self.lock:
            return self._parents(path, depth=depth)

    def _parents(self, path, depth=0):
        path = self.path_sep + path.lstrip(self.path_sep)
        max_depth = len(path.split(self.path_sep))
        if depth == 0 or depth > max_depth:
            depth = max_depth
        parent_path = self._dir_name(path)
        infos = self._list(parent_path)
        _parents = list(filter(lambda x: x['mime'] == 'directory', infos))
        if self._is_root(parent_path):
            _parents.append(self._info(self.path_sep))
        if depth == 1:
            return _parents
        parents = _parents + self._parents(parent_path, depth - 1)
        return parents

    def read_file_view(self, request, target, download=True):
        remote_path = self._remote_path_h(target)
        f = self.sftp.open(remote_path, 'r')
        filename = self._base_name(remote_path)
        response = send_file(f, mimetype='application/octet-stream',
                             as_attachment=True, attachment_filename=filename)
        return response

    def mkdir(self, names, parent, many=False):
        """ Creates a new directory. """
        parent_path = self._path(parent)
        data = []
        if not many:
            names = [names]
        for name in names:
            path = self._join(parent_path, name)
            remote_path = self._remote_path(path)
            self.sftp.mkdir(remote_path)
            data.append(self._info(path))
        return data

    def mkfile(self, name, parent):
        """ Creates a new file. """
        parent_path = self._path(parent)
        path = self._join(parent_path, name)
        remote_path = self._remote_path(path)

        with self.sftp.open(remote_path, mode='w'):
            pass
        return self._info(path)

    def rename(self, name, target):
        """ Renames a file or directory. """
        path = self._path(target)
        remote_path = self._remote_path(path)
        new_path = self._join(self._dir_name(path), name)
        new_remote_path = self._remote_path(new_path)
        self.sftp.rename(remote_path, new_remote_path)
        return {
            'added': [self._info(new_path)],
            'removed': [target]
        }

    def is_exist(self, path):
        remote_path = self._remote_path(path)
        try:
            data = self.sftp.lstat(remote_path)
            exist = True
        except FileNotFoundError:
            exist = False
        return exist

    def is_dir(self, path):
        info = self._info(path)
        if info['mime'] == 'directory':
            return True
        else:
            return False

    def paste(self, targets, dest, cut):
        """ Moves/copies target files/directories from source to dest. """
        dest_parent_path = self._path(dest)
        added = []
        removed = []

        for target in targets:
            src_path = self._path(target)
            dest_path = self._join(dest_parent_path, self._base_name(src_path))
            if self.is_dir(src_path):
                raise OSError("Copy folder unsupported now")
            if self.is_exist(dest_path):
                continue
            src_remote_path = self._remote_path(src_path)
            dest_remote_path = self._remote_path(dest_path)
            f = self.sftp.open(src_remote_path, mode='r')
            try:
                attr = self.sftp.putfo(f, dest_remote_path)
                if cut:
                    removed.append(self.remove(target))
                added.append(self._info(dest_path, attr))
            finally:
                f.close()

        return {"added": added, "removed": removed}

    def remove(self, target):
        """ Delete a File or Directory object. """
        path = self._path(target)
        remote_path = self._remote_path(path)
        try:
            info = self.info(target)
            if info['mime'] == 'directory':
                self.sftp.rmdir(remote_path)
            else:
                self.sftp.unlink(remote_path)
        except OSError:
            raise OSError("Delete {} failed".format(self._base_name(path)))
        return target

    def upload_as_url(self, url, parent):
        raise PermissionError("Not support upload from url")

    def upload(self, files, parent):
        """ For now, this uses a very naive way of storing files - the entire
            file is read in to the File model's content field in one go.

            This should be updated to use read_chunks to add the file one 
            chunk at a time.
        """
        added = []
        parent_path = self._path(parent)
        item = files.get('upload[]')
        path = self._join(parent_path, item.filename)
        remote_path = self._remote_path(path)
        infos = self._list(parent_path)
        files_exist = [d['name'] for d in infos]
        if item.filename in files_exist:
            raise OSError("File {} exits".format(remote_path))
        with self.sftp.open(remote_path, 'w') as rf:
            for data in item:
                rf.write(data)
        added.append(self._info(path))
        return {'added': added}

    def upload_as_chunk(self, files, chunk_name, parent):
        added = []
        parent_path = self._path(parent)
        item = files.get('upload[]')
        __tmp = chunk_name.split('.')
        filename = '.'.join(__tmp[:-2])
        num, total = __tmp[-2].split('_')
        num, total = int(num), int(total)

        path = self._join(parent_path, filename)
        remote_path = self._remote_path(path)
        if num == 0:
            infos = self._list(parent_path)
            files_exist = [d['name'] for d in infos]
            if item.filename in files_exist:
                raise OSError("File {} exits".format(remote_path))
        with self.sftp.open(remote_path, 'a') as rf:
            for data in item:
                rf.write(data)
        if num != total:
            return {'added': added}
        else:
            return {'added': added, '_chunkmerged': filename, '_name': filename}

    def upload_chunk_merge(self, parent, chunk):
        parent_path = self._path(parent)
        path = self._join(parent_path, chunk)
        return {"added": [self._info(path)]}

    def size(self, target):
        info = self.info(target)
        return info.get('size') or 'Unknown'
