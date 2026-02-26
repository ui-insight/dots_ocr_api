import requests

url = "https://dotsocr.nkn.uidaho.edu/dotsocr"
with open("document.pdf", "rb") as f:
    r = requests.post(url, files={"file": f})

print(r.text)
