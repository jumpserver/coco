#!/bin/bash

if grep -q 'source ~/.autoenv/activate.sh' ~/.bashrc; then
    echo -e "\033[31m 正在自动载入 python 环境 \033[0m"
else
    echo -e "\033[31m 不支持自动升级，请参考 http://docs.jumpserver.org/zh/docs/upgrade.html 手动升级 \033[0m"
    exit 0
fi

source ~/.bashrc

cd `dirname $0`/ && cd .. && ./cocod stop

coco_backup=/tmp/coco_backup$(date -d "today" +"%Y%m%d_%H%M%S")
mkdir -p $coco_backup
cp -r ./* $coco_backup

git pull && pip install -r requirements/requirements.txt

./cocod start -d
echo -e "\033[31m 请检查coco是否启动成功 \033[0m"
echo -e "\033[31m 备份文件存放于$coco_backup目录 \033[0m"

exit 0
