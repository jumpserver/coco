FROM jumpserver/python:v3
MAINTAINER Jumpserver Team <ibuler@qq.com>

COPY . /opt/coco
WORKDIR /opt/coco

RUN cd requirements && yum -y install $(cat rpm_requirements.txt) && \
   pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

VOLUME /opt/coco/logs
VOLUME /opt/coco/keys

RUN cp config_docker.py config.py

EXPOSE 2222
CMD python run_server.py