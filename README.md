# Coco

Coco is a sub app of Jumpserver.

It's implement a ssh server 

User can connect them except openssh server and connect.py pre version.


## Install

    $ git clone https://github.com/jumpserver/coco.git
    $ pip install -r requirements.txt -i https://pypi.doubanio.com/simple
    
## Setting

You need update config.py settings as you need, Be aware of: 

*YOU MUST SET SOME CONFIG THAT CONFIG POINT*

They are:

    NAME:  # This name will be use register as app user default coco
    JUMPSERVER_URL:  # Jumpserver endport, will connect it for auth or other default https://localhost:8080
    
More see config.py


## Start

    # python run_server.py
    
When your start ssh server, It will register with jumpserver api,

Then you need login jumpserver with admin user, active it in <Terminal>
 
 If all done, your can use your ssh tools connect it.
 
ssh user@host:port

