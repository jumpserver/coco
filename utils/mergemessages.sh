# mergemessages -> pot po
# 

xgettext -k_ -o pot/coco.pot --from-code=UTF-8 coco/*.py
msgmerge -U locale/zh_CN/LC_MESSAGES/coco.po pot/coco.pot
msgmerge -U locale/en/LC_MESSAGES/coco.po pot/coco.pot

