FROM registry.fit2cloud.com/jumpserver/python:v3
MAINTAINER Jumpserver Team <ibuler@qq.com>

COPY requirements /opt/coco/requirements
WORKDIR /opt/coco

RUN cd requirements && yum -y install $(cat rpm_requirements.txt) && \
   pip install -r requirements.txt
COPY . /opt/coco
VOLUME /opt/coco/logs
VOLUME /opt/coco/keys

RUN cp conf_docker.py conf.py

EXPOSE 2222
CMD python run_server.py