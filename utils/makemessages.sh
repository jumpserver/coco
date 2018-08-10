# makemassages -> .pot .po
# 

xgettext -k_ -o pot/coco.pot --from-code=UTF-8 coco/*.py
msginit -l locale/zh_CN/LC_MESSAGES/coco -i pot/coco.pot
msginit -l locale/en/LC_MESSAGES/coco -i pot/coco.pot

