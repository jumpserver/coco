#!/bin/bash

if [ ! -d "/opt/py3" ]; then
echo -e "\033[31m python3虚拟环境不是默认路径 \033[0m"
ps -ef | grep jumpserver/tmp/beat.pid | grep -v grep
if [ $? -ne 0 ]
then
echo -e "\033[31m jumpserver未运行，请到jumpserver目录使用 ./jms start all -d 启动 \033[0m"
exit 0
else 
echo -e "\033[31m 正在计算python3虚拟环境路径 \033[0m"
fi
py3pid=`ps -ef | grep jumpserver/tmp/beat.pid | grep -v grep | awk '{print $2}'`
py3file=`cat /proc/$py3pid/cmdline`
py3even=`echo ${py3file%/bin/python3*}`
echo -e "\033[31m python3虚拟环境路径为$py3even \033[0m"
source $py3even/bin/activate
else
source /opt/py3/bin/activate
fi

cd `dirname $0`/ && cd .. && ./cocod stop

coco_backup=/tmp/coco_backup$(date -d "today" +"%Y%m%d_%H%M%S")
mkdir -p $coco_backup
cp -r ./* $coco_backup

git pull && pip install -r requirements/requirements.txt

./cocod start -d
echo -e "\033[31m 请检查coco是否启动成功 \033[0m"
echo -e "\033[31m 备份文件存放于$coco_backup目录 \033[0m"

exit 0
