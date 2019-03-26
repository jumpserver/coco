import logging

logger = logging.getLogger(__name__)


class ElFinderConnector:
    """ Connector class for Django/elFinder integration.

        Permissions checks when viewing/modifying objects - users can currently
        create files in other people's file collections, or delete files they
        do not own. This needs to be implemented in an extendable way, rather
        than being tied to one method of permissions checking.
    """
    _version = '2.1'

    _supported_commands = {
        'open': ('__open', {'target': True}),
        'tree': ('__tree', {'target': True}),
        'file': ('__file', {'target': True}),
        'parents': ('__parents', {'target': True}),
        'mkdir': ('__mkdir', {'target': True}),
        'mkfile': ('__mkfile', {'target': True, 'name': True}),
        'rename': ('__rename', {'target': True, 'name': True}),
        'ls': ('__list', {'target': True}),
        'paste': ('__paste', {'targets[]': True, 'dst': True, 'cut': True}),
        'rm': ('__remove', {'targets[]': True}),
        'upload': ('__upload', {'target': True}),
        'size': ('__size', {'targets[]': True}),
    }

    _allowed_args = [
        'cmd', 'target', 'targets[]', 'current', 'tree',
        'name', 'content', 'src', 'dst', 'cut', 'init',
        'type', 'width', 'height', 'upload[]', 'dirs[]',
        'targets', "chunk", "range", "cid", 'reload',
    ]

    _options = {
        'api': _version,
        'uplMaxSize': '10M',
        'options': {
            'separator': '/',
            'archivers': {
                'create': [],
                'extract': []
            },
            'copyOverwrite': 1,
            'uiCmdMap': [],
            "disabled": [
                "chmod"
            ],
        },
    }

    def __init__(self, volumes=None):
        self.response = {}
        self.status_code = 200
        self.headers = {'Content-type': 'application/json'}

        self.data = {}
        self.return_view = None
        self.volumes = {}
        self.request = None
        for volume in volumes:
            self.volumes[volume.get_volume_id()] = volume

    def get_volume(self, _hash):
        """ Returns the volume which contains the file/dir represented by the
            hash.
        """
        try:
            volume_id, target = _hash.split('_', 1)
        except ValueError:
            raise Exception('Invalid target hash: %s' % hash)
        return self.volumes[volume_id]

    def check_command_args(self, args):
        """ Checks the GET variables to ensure they are valid for this command.
            _commands controls which commands must or must not be set.

            This means command functions do not need to check for the presence
            of GET vars manually - they can assume that required items exist.
        """
        for field in args:
            if args[field] is True and field not in self.data:
                return False
        return True

    def run_command(self, func_name, args):
        """ Attempts to run the given command.

            If the command does not execute, or there are any problems
            validating the given GET vars, an error message is set.

            func: the name of the function to run (e.g. __open)
            command_variables: a list of 'name':True/False tuples specifying
            which GET variables must be present or empty for this command.
        """
        if not self.check_command_args(args):
            self.response['error'] = 'Invalid arguments'
            print("++++++++++++++++++++++++++++++++ not valid")
            return

        func = getattr(self, '_' + self.__class__.__name__ + func_name, None)
        if not callable(func):
            self.response['error'] = 'Command failed'
            return

        try:
            func()
        except Exception as e:
            self.response['error'] = '%s' % e
            logger.error(e, exc_info=True)

    def get_request_data(self):
        data_source = {}
        if self.request.method == 'POST':
            data_source = self.request.values
        elif self.request.method == 'GET':
            data_source = self.request.args
        return data_source

    def get_request_commands(self):
        request_data = self.get_request_data()
        # Copy allowed parameters from the given request's GET to self.data
        for field in self._allowed_args:
            if field in request_data:
                if field in ["targets[]", "targets", "dirs[]"]:
                    self.data[field] = request_data.getlist(field)
                else:
                    self.data[field] = request_data[field]
        if 'cmd' in self.data and self._supported_commands:
            cmd = self._supported_commands[self.data['cmd']]
            return cmd
        else:
            self.response['error'] = 'No valid command found'
            return None, None

    def run(self, request):
        """ Main entry point for running commands. Attemps to run a command
            function based on info in request.GET.

            The command function will complete in one of two ways. It can
            set response, which will be turned in to an HttpResponse and
            returned to the client.

            Or it can set return_view, a Django View function which will
            be rendered and returned to the client.
        """
        self.request = request
        func_name, args = self.get_request_commands()
        if not func_name:
            self.response['error'] = 'No command specified'
        else:
            self.run_command(func_name, args)

    def __parents(self):
        """ Handles the parent command.

            Sets response['tree'], which contains a list of dicts representing
            the ancestors/siblings of the target object.

            The tree is not a tree in the traditional hierarchial sense, but
            rather a flat list of dicts which have hash and parent_hash (phash)
            values so the client can draw the tree.
        """
        target = self.data['target']
        volume = self.get_volume(target)
        self.response['tree'] = volume.parents(target, depth=1)

    def __tree(self):
        """ Handles the 'tree' command.

            Sets response['tree'] - a list of children of the specified
            target Directory.
        """
        target = self.data['target']
        volume = self.get_volume(target)
        self.response['tree'] = volume.tree(target)

    def __file(self):
        """ Handles the 'file' command.

            Sets return_view, which will cause read_file_view to be rendered
            as the response. A custom read_file_view can be given when
            initialising the connector.
        """
        target = self.data['target']
        download = self.data.get("download", False)
        volume = self.get_volume(target)

        # A file was requested, so set return_view to the read_file view.
        #self.return_view = self.read_file_view(self.request, volume, target)
        self.return_view = volume.read_file_view(self.request, target, download=download)

    def __open(self):
        """ Handles the 'open' command.

            Sets response['files'] and response['cwd'].

            If 'tree' is requested, 'files' contains information about all
            ancestors, siblings and children of the target. Otherwise, 'files'
            only contains info about the target's immediate children.

            'cwd' contains info about the currently selected directory.

            If 'target' is blank, information about the root dirs of all
            currently-opened volumes is returned. The root of the first
            volume is considered to be the current directory.
        """
        target = self.data['target']
        if target == '':
            volume = list(self.volumes.values())[0]
        else:
            volume = self.get_volume(target)
        self.response['cwd'] = volume.info(target)
        files = volume.list(target)
        if 'tree' in self.data or 'reload' in self.data:
            parents = volume.parents(target, depth=0)
            parents = filter(lambda x: x not in files, parents)
            files += parents
        self.response['files'] = files
        if 'init' in self.data:
            self.response.update(self._options)
        else:
            self.response['options'] = self._options['options']

    def __mkdir(self):
        target = self.data['target']
        volume = self.get_volume(target)
        if self.data.get('name'):
            self.response['added'] = volume.mkdir(self.data['name'], target)
        elif self.data.get('dirs[]'):
            self.response['added'] = volume.mkdir(self.data['dirs[]'], target, many=True)
        else:
            self.response['error'] = "Not found dir name"

    def __mkfile(self):
        target = self.data['target']
        volume = self.get_volume(target)
        self.response['added'] = [volume.mkfile(self.data['name'], target)]

    def __rename(self):
        target = self.data['target']
        volume = self.get_volume(target)
        self.response.update(volume.rename(self.data['name'], target))

    def __list(self):
        target = self.data['target']
        volume = self.get_volume(target)
        self.response['list'] = volume.list(target, name_only=True)

    def __paste(self):
        targets = self.data['targets[]']
        dest = self.data['dst']
        cut = self.data['cut'] == '1'
        dest_volume = self.get_volume(dest)
        self.response.update(dest_volume.paste(targets, dest, cut))

    def __remove(self):
        targets = self.data['targets[]']
        self.response['removed'] = []
        # Because the targets might not all belong to the same volume, we need
        # to lookup the volume and call the remove() function for every target.
        for target in targets:
            volume = self.get_volume(target)
            self.response['removed'].append(volume.remove(target))

    def __upload(self):
        parent = self.data['target']
        volume = self.get_volume(parent)
        upload = self.data.get('upload[]')
        if self.data.get('chunk') and self.data.get('cid'):
            self.response.update(
                volume.upload_as_chunk(
                    self.request.files, self.data.get('chunk'), parent
                )
            )
        elif self.data.get('chunk'):
            self.response.update(
                volume.upload_chunk_merge(parent, self.data.get('chunk'))
            )
        elif isinstance(upload, str):
            self.response.update(volume.upload_as_url(upload, parent))
        else:
            self.response.update(volume.upload(self.request.files, parent))

    def __size(self):
        target = self.data['targets[]']
        volume = self.get_volume(target)
        self.response['size'] = volume.size(target)
