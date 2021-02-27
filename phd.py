import json
import os
import requests
import re

from urllib.parse import urlparse
from html.parser import unescape


def init_proxy(proxy):
    os.environ["ALL_PROXY"] = proxy


def init_dir(path):
    if not os.path.exists(path):
        os.mkdir(path)


class Config:
    path = "config.json"

    def __init__(self):
        self.data = {}

    def write_config(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f)

    def load_config(self):
        with open(self.path, "r") as f:
            self.data = json.load(f)


class Base:
    @staticmethod
    def fetch_url(url, cookie):
        return requests.get(url, headers={"cookie": cookie}).content.decode("utf-8")

    @staticmethod
    def post_url(url, cookie, body):
        return requests.post(url, json=body, headers={"cookie": cookie}).content.decode("utf-8")

    @staticmethod
    def stream_download(url, path):
        total = 0
        with open(path, "wb") as f:
            with requests.get(url, stream=True) as r:
                for chunk in r.iter_content(1024):
                    total += len(chunk)
                    mb = round(float(total) / 1024 / 1024, 2)
                    print("\b" * 100 + f"{mb} MB......", end="")
                    f.write(chunk)
        print("\n")

    def run(self, url, cookie):
        raise NotImplemented

    def prompt_download_option(self):
        raise NotImplemented

    def run_download(self, i, dirpath):
        raise NotImplemented


class PHD(Base):
    domain = "pornhub.com"

    def __init__(self):
        self.title = ""
        self.content = ""
        self.option = []

    def _get_core_js(self):
        match = re.findall(r"<script type=\"text/javascript\">(?P<js>[\s\S]*?)</script>", self.content, re.MULTILINE)
        for s in match:
            if "flashvar" in s:
                return s
        return ""

    def _get_title(self):
        match = re.search(r"<meta property=\"og:title\" content=\"(?P<title>.*?)\" />", self.content).groupdict()
        self.title = match.get("title")

    def _parse_js_variables(self, js):
        lines_with_semi = js.splitlines()
        lines_with_semi = [l.strip() for l in lines_with_semi]
        lines_with_semi = [l for l in lines_with_semi if l]

        lines = []
        for li in lines_with_semi:
            for s in li.split(";"):
                if s:
                    lines.append(s)

        var_dict = {}
        media_dict = {}

        for li in lines:
            if li.startswith("var ra"):
                var, val = li.split("=", 1)
                var = var.replace("var ", "")
                val = val.replace("\" + \"", "")
                val = val.strip("\"")
                var_dict[var] = val
            elif li.startswith("var media"):
                k, v = self._build_media_url(li, var_dict)
                media_dict[k] = v

        return list(media_dict.values())

    def _build_media_url(self, line, vars):
        var_name, val = line.split("=", 1)
        var_name = var_name.replace("var ", "")

        s = ""
        comment = False
        idx = 0
        while idx < len(val):
            if val[idx] == "/":
                idx += 1
                comment = True
            elif val[idx] == "*":
                idx += 1
                comment = False
            elif comment:
                pass
            else:
                s += val[idx]
            idx += 1

        rv = ""
        keys = s.split("+")
        keys = [v.strip() for v in keys]
        for v in keys:
            rv += vars.get(v)

        return var_name, rv

    def prompt_download_option(self):
        print("choose quality:\n")
        for i, dct in enumerate(self.option):
            qual = int(dct["quality"])
            fmt = dct["format"]

            print(f"{i}) {qual}p {fmt}")

        while True:
            choice = input("type number: ")
            try:
                i = int(choice.strip())
            except Exception:
                pass
            else:
                break
        return i

    def run(self, url, cookie):
        self.content = self.fetch_url(url, cookie)
        self._get_title()
        js_segment = self._get_core_js()
        opt_urls = self._parse_js_variables(js_segment)

        opt_urls = [url for url in opt_urls if "get_media" in url]
        if not opt_urls:
            return
        info_url = opt_urls[0]

        info = self.fetch_url(info_url, cookie)

        data = json.loads(info)
        self.option = data

    def run_download(self, i, dirpath):
        download_url = self.option[i]["videoUrl"]
        fmt = self.option[i]["format"]
        qual = self.option[i]["quality"]

        if not download_url:
            return

        name = f"{self.title}_{qual}.{fmt}"
        path = os.path.join(dirpath, name)

        self.stream_download(download_url, path)

        return path


class XVD(Base):
    domain = "xvideos.com"

    def __init__(self):
        self.title = ""
        self.content = ""
        self.option = []

    def _get_title(self):
        match = re.search(r"<meta property=\"og:title\" content=\"(?P<title>.*?)\" />", self.content).groupdict()
        self.title = unescape(match.get("title"))

    def run(self, url, cookie):
        self.content = self.fetch_url(url, cookie)
        self._get_title()

        vd_number = urlparse(url).path.split("/")[1][5:]

        post_content = self.post_url(f"https://www.xvideos.com/video-download/{vd_number}/", cookie, {})
        data = json.loads(post_content)

        for k, v in data.items():
            if type(v) == str and v.startswith("http"):
                self.option.append([k, v])
        return

    def prompt_download_option(self):
        print("choose quality:\n")

        for i, tup in enumerate(self.option):
            key, url = tup

            print(f"{i}) {key} {url}")

        while True:
            choice = input("type number: ")
            try:
                i = int(choice.strip())
            except Exception:
                pass
            else:
                break
        return i

    def run_download(self, i, dirpath):
        download_url = self.option[i][1]
        if not download_url:
            return

        name = f"{self.title}.mp4"
        path = os.path.join(dirpath, name)

        self.stream_download(download_url, path)

        return path


class PornDownloader:
    domain_class = {
        cls.domain: cls for cls in [PHD, XVD]
    }

    def __init__(self, url, cfg):
        self.url = url
        self.domain_instance = None
        self.domain = self.detect_domain()

        cls = self.domain_class[str(self.domain)]
        self.domain_instance = cls()

        self.cfg = cfg

        self.cookie = self.cfg["cookies"][self.domain]

    def detect_domain(self):
        netloc = urlparse(self.url).netloc
        domain = netloc.split(".", 1)[1]
        return domain

    def run(self):
        self.domain_instance.run(self.url, self.cookie)
        choice = self.domain_instance.prompt_download_option()
        pth = self.domain_instance.run_download(choice, self.cfg["download_path"])
        return pth


def main():
    cfg = Config()
    cfg.load_config()

    init_dir(cfg.data["download_path"])
    init_proxy(cfg.data["all_proxy"])

    print("initialized\n")

    while True:
        url = input("video url: ")
        url = url.strip()

        try:
            pd = PornDownloader(url, cfg.data)
            pth = pd.run()
        except Exception as e:
            print(e)
        else:
            print(f"download finish <{pth}> \n")


if __name__ == '__main__':
    main()
