# -*- coding: utf-8 -*-
#

from flask import render_template, request, jsonify

from .app import app
from .finder import connector, volumes
from ..models import Connection
from ..sftp import InternalSFTPClient
from .auth import login_required
from ..service import app_service


@app.route('/elfinder/sftp/connector/<host>/', methods=['GET', 'POST'])
@login_required
def sftp_host_connector_view(host):
    user = request.current_user
    connection = Connection(addr=(request.real_ip, 0))
    connection.user = user
    sftp = InternalSFTPClient(connection)
    volume = volumes.SFTPVolume(sftp)
    if host:
        asset = app_service.get_asset(host)
        if not asset:
            return jsonify({'error': 'Not found this host'})
        hostname = asset.hostname
        if asset.org_id:
            hostname = "{}.{}".format(asset.hostname, asset.org_name)
        volume.root_name = hostname
        volume.base_path = '/' + hostname
    handler = connector.ElFinderConnector([volume])
    handler.run(request)

    # Some commands (e.g. read file) will return a Django View - if it
    # is set, return it directly instead of building a response
    if handler.return_view:
        return handler.return_view

    if handler.headers['Content-type'] == 'application/json':
        return jsonify(handler.response)


@app.route('/elfinder/sftp/connector/', methods=['GET', 'POST'])
@login_required
def sftp_connector_view():
    return sftp_host_connector_view('')


@app.route('/elfinder/sftp/<host>/')
def sftp_host_finder(host):
    return render_template('finder/host_file_manager.html', host=host)


@app.route('/elfinder/sftp/')
def sftp_finder():
    return render_template('finder/file_manager.html')


