#!/bin/bash
#

function init_message() {
    xgettext -k_ -o /tmp/coco.pot --from-code=UTF-8 coco/*.py
    msginit -l locale/zh_CN/LC_MESSAGES/coco -i /tmp/coco.pot
    msginit -l locale/en/LC_MESSAGES/coco -i /tmp/coco.pot
}

function make_message() {
    xgettext -k_ -o /tmp/coco.pot --from-code=UTF-8 coco/*.py
    msgmerge -U locale/zh_CN/LC_MESSAGES/coco.po /tmp/coco.pot
    msgmerge -U locale/en/LC_MESSAGES/coco.po /tmp/coco.pot
}

function compile_message() {
   msgfmt -o locale/zh_CN/LC_MESSAGES/coco.mo locale/zh_CN/LC_MESSAGES/coco.po
   msgfmt -o locale/en/LC_MESSAGES/coco.mo locale/en/LC_MESSAGES/coco.po
}

action=$1
if [ -z "$action" ];then
    action="make"
fi

case $action in
    m|make)
        make_message;;
    i|init)
        init_message;;
    c|compile)
        compile_message;;
    *)
        echo "Usage: $0 [m|make i|init | c|compile]"
        exit 1
        ;;
esac

