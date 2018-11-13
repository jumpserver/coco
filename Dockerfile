FROM registry.fit2cloud.com/public/python:v3
MAINTAINER Jumpserver Team <ibuler@qq.com>

COPY requirements /opt/coco/requirements
WORKDIR /opt/coco

RUN yum -y install epel-release
RUN cd requirements && yum -y install $(cat rpm_requirements.txt)
RUN cd requirements && pip install $(egrep "jumpserver|jms" requirements.txt | tr '\n' ' ') && pip install -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/web/simple

ENV LANG=zh_CN.UTF-8
ENV LC_ALL=zh_CN.UTF-8

COPY . /opt/coco
VOLUME /opt/coco/logs
VOLUME /opt/coco/keys

RUN cp conf_docker.py conf.py

EXPOSE 2222
CMD python run_server.py
