FROM wojiushixiaobai/python3.6.1:latest
LABEL maintainer "wojiushixiaobai"
WORKDIR /opt

COPY . /opt/coco/

RUN set -ex \
    && localedef -c -f UTF-8 -i zh_CN zh_CN.UTF-8 \
    && export LC_ALL=zh_CN.UTF-8 \
    && echo 'LANG="zh_CN.UTF-8"' > /etc/locale.conf \
    && yum -y install $(cat /opt/coco/requirements/rpm_requirements.txt) \
    && python3 -m venv /opt/py3 \
    && source /opt/py3/bin/activate \
    && pip install -r /opt/coco/requirements/requirements.txt \
    && yum clean all \
    && rm -rf /var/cache/yum/* \
    && rm -rf ~/.cache/pip \
    && mkdir -p /opt/coco/keys \
    && mkdir -p /opt/coco/logs \
    && cp /opt/coco/conf_example.py /opt/coco/conf.py \
    && sed -i "s/# CORE_HOST/CORE_HOST/g" `grep "# CORE_HOST" -rl /opt/coco/conf.py` \
    && sed -i "s/# LOG_LEVEL = 'INFO'/LOG_LEVEL = 'ERROR'/g" `grep "# LOG_LEVEL = 'INFO'" -rl /opt/coco/conf.py`


COPY entrypoint.sh /bin/entrypoint.sh
RUN chmod +x /bin/entrypoint.sh

VOLUME /opt/coco/keys

ENV NAME=coco \
    CORE_HOST=http://127.0.0.1:8080

EXPOSE 2222 5000
ENTRYPOINT ["entrypoint.sh"]
