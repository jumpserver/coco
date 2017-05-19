FROM jumpserver/python:v3.6.1
LABEL MAINTAINER Jumpserver Team <ibuler@qq.com>

COPY . /opt/coco
WORKDIR /opt/coco

RUN cd requirements && yum -y install $(cat rpm_requirements.txt)
RUN cd requirements && pip install -r requirements.txt
RUN yum clean all

VOLUME /opt/coco/logs
VOLUME /opt/coco/keys

RUN rm -r .git
RUN rm -f keys/.access_key

RUN cp config_docker.py config.py

EXPOSE 2222
CMD python run_server.py