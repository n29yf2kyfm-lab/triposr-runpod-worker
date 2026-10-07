import json,sys,os
HERE=os.path.dirname(os.path.abspath(__file__))
T={t['code']:t for t in json.load(open(os.path.join(HERE,'targets.json')))}
with open(os.path.join(HERE,'skip.txt'),'a') as f:
    for c in sys.argv[1:]:
        t=T[c]; line=f"{c}   {t['make']} {t['gen']} ({t['from']}-{t['to']})"
        f.write(line+'\n'); print(line)
