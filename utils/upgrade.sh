#!/bin/bash

if [ ! -d "/opt/py3" ]; then
echo -e "\033[31m python3虚拟路径不正确 \033[0m"
echo -e "\033[31m 请手动修改虚拟环境的位置 \033[0m"
exit 0
else
source /opt/py3/bin/activate
fi

cd `dirname $0`/ && cd .. && ./cocod stop

coco_backup=/tmp/coco_backup$(date -d "today" +"%Y%m%d_%H%M%S")
mkdir -p $coco_backup
cp -r ./* $coco_backup

git pull && pip install -r requirements/requirements.txt

echo -e "\033[31m 备份文件存放于$coco_backup目录 \033[0m"

exit 0
