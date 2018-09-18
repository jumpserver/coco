import logging
import stat
import re

from flask import send_file

from .base import BaseVolume


logger = logging.getLogger(__name__)


class SFTPVolume(BaseVolume):
    def __init__(self, sftp):
        self.sftp = sftp
        self.root_name = 'Home'
        super().__init__()
        self._stat_cache = {}

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
            "ts": 0,
            "size": 'unknown',
            "mime": "directory" if stat.S_ISDIR(attr.st_mode) else "file",
            "locked": 0,
            "hidden": 0,
            "read": 1,
            "write": 1,
        }
        if data["mime"] == 'directory':
            data["dirs"] = 1

        if self._is_root(path):
            del data['phash']
            data['name'] = self.root_name
            data['locked'] = 1
            data['volume_id'] = self.get_volume_id()
        # print("_Get stat info end")
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
        # print("List {}-{}".format(target, path))
        return self._list(path)

    def tree(self, target):
        """ Get the sub directory of directory
        """
        path = self._path(target)
        # print("Tree {} {}".format(target, path))
        infos = self.list(target)
        tree = list(filter(lambda x: x['mime'] == 'directory', infos))
        return tree

    def parents(self, target, depth=0):
        """
        获取目录的父目录, 如果deep为0，则直到根
        """
        path = self._path(target).rstrip(self.path_sep)
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
        remote_path = self._remote_path(parent_path)
        with self.sftp.open(remote_path, mode='w'):
            pass
        return self._info(parent_path)

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

    def paste(self, targets, source, dest, cut):
        """ Moves/copies target files/directories from source to dest. """
        return {"error": "Not support paste"}

    def remove(self, target):
        """ Delete a File or Directory object. """
        path = self._path(target)
        remote_path = self._remote_path(path)
        try:
            self.sftp.unlink(remote_path)
        except OSError:
            raise OSError("Delete {} failed".format(self._base_name(path)))
        return target

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
        print("Upload chunk: {}".format(chunk_name))
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
