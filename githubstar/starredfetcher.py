import concurrent.futures
import logging
import os
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from githubstar import utils


class TopicInfo:
    name = ""
    url = ""


class RepoInfo:
    full_name = ""
    name = ""
    html_url = ""
    description = ""
    language = ""
    stargazers_count = 0
    forks_count = 0
    pushed_at = datetime.fromisoformat("1970-01-01T11:11:11")


class ListInfo:
    name = ""
    url = ""
    description = ""
    count = 0
    repos = []


class StarredFetcher(object):
    def __init__(self, username):
        self.username = username
        self.starredTopics = []
        self.starredLists = []
        self.fetchListReposTaskDatas = []

    def fetchTopics(self):
        url = ""
        try:
            url = "https://github.com/stars/{username}/topics?direction=desc&page={page}&sort=created"
            page = 1
            itemsPerPage = 0
            while True:
                response = requests.get(url.format(username=self.username, page=page))
                response.raise_for_status()
                soup = BeautifulSoup(
                    response.text, "html.parser", multi_valued_attributes=None
                )
                listsContainer = soup.find(
                    "ul",
                    class_="repo-list list-style-none js-navigation-container js-active-navigation-container",
                )
                if listsContainer:
                    curItemsPerPage = 0
                    for li in listsContainer.find_all("li"):
                        topicInfo = TopicInfo()
                        topicInfo.url = "https://github.com" + li.find(
                            "a",
                            class_="d-flex flex-md-items-center flex-auto no-underline",
                        ).get("href")
                        topicInfo.name = li.find(
                            "p", class_="f3 lh-condensed mt-1 mt-md-0 mb-0"
                        ).text
                        self.starredTopics.append(topicInfo)
                        curItemsPerPage += 1
                    if itemsPerPage <= 0:
                        itemsPerPage = curItemsPerPage
                    elif curItemsPerPage < itemsPerPage:
                        break
                else:
                    break
                page += 1
        except Exception as exception:
            logging.error(
                f"{__class__} line {exception.__traceback__.tb_lineno} : {url} generated an exception: {exception}"
            )

    def fetch(self):
        try:
            url = f"https://github.com/{self.username}?tab=stars"
            response = requests.get(url)
            response.raise_for_status()
            utils.printProgress(3)
            soup = BeautifulSoup(
                response.text, "html.parser", multi_valued_attributes=None
            )
            if soup.find("div", class_="col-lg-3 mt-6 mt-lg-0"):
                self.fetchTopics()
            utils.printProgress(5)
            listsContainer = soup.find(id="profile-lists-container")
            if listsContainer:
                for link in listsContainer.find_all("a"):
                    listInfo = ListInfo()
                    name = link.find(class_="f4 text-bold no-wrap mr-3")
                    if name:
                        listInfo.name = name.text.strip()
                    listInfo.url = "https://github.com" + link.get("href")
                    description = link.find(class_="Truncate-text color-fg-muted mr-3")
                    if description:
                        listInfo.description = description.text.strip()
                    count = link.find(class_="color-fg-muted text-small no-wrap")
                    if count:
                        matchObj = re.match(r"(\d+)[\s+]repositor[y|ies]", count.text)
                        if matchObj:
                            listInfo.count = int(matchObj.group(1))
                            listInfo.repos = [RepoInfo()] * listInfo.count
                    self.starredLists.append(listInfo)
                self.getReposPerPage()
                utils.printProgress(8)
                self.buildFetchListReposTaskDatas()
                self.fetchListRepos()
        except Exception as exception:
            logging.error(
                f"{__class__} line {exception.__traceback__.tb_lineno} : {url} generated an exception: {exception}"
            )

    __REPOS_PER_PAGE = 30

    def getReposPerPage(self):
        try:
            reposPerPage = 0
            maxCount = 0
            maxCountIndex = 0
            curIndex = 0
            for listInfo in self.starredLists:
                if listInfo.count > 0 and listInfo.count > maxCount:
                    maxCount = listInfo.count
                    maxCountIndex = curIndex
                curIndex += 1
            response = requests.get(self.starredLists[maxCountIndex].url + "?page=1")
            response.raise_for_status()
            soup = BeautifulSoup(
                response.text, "html.parser", multi_valued_attributes=None
            )
            reposContainer = soup.find(id="user-list-repositories")
            if reposContainer:
                reposPerPage = len(
                    reposContainer.find_all(
                        "div",
                        class_="col-12 d-block width-full py-4 border-bottom color-border-muted",
                    )
                )
            if reposPerPage > 0:
                __REPOS_PER_PAGE = reposPerPage
        except Exception as exception:
            logging.error(
                f"{__class__} line {exception.__traceback__.tb_lineno} : {exception}"
            )

    class FetchListReposTaskData:
        def __init__(self, listInfo, page_url, page_first_repo_index):
            self.listInfo = listInfo
            self.page_url = page_url
            self.page_first_repo_index = page_first_repo_index

    def buildFetchListReposTaskDatas(self):
        for listInfo in self.starredLists:
            if listInfo.count > 0:
                totalPage = (
                    listInfo.count + self.__REPOS_PER_PAGE - 1
                ) // self.__REPOS_PER_PAGE
                url = listInfo.url + "?page={page}"
                page = 1
                while page <= totalPage:
                    page_url = url.format(page=page)
                    page_first_repo_index = (page - 1) * self.__REPOS_PER_PAGE
                    self.fetchListReposTaskDatas.append(
                        StarredFetcher.FetchListReposTaskData(
                            listInfo, page_url, page_first_repo_index
                        )
                    )
                    page += 1

    def fetchListRepos(self):
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(32, (os.process_cpu_count() or 1) * 2)
        ) as executor:
            future_to_task = {
                executor.submit(self.fetchListReposTask, data): data
                for data in self.fetchListReposTaskDatas
            }
            for future in concurrent.futures.as_completed(future_to_task):
                data = future_to_task[future]
                result = future.result()

    __fetchListReposTask_lastExceptionLineNo = 0
    __fetchListReposTask_lastExceptionType = None

    def fetchListReposTask(self, data):
        try:
            response = requests.get(data.page_url)
            response.raise_for_status()
            soup = BeautifulSoup(
                response.text, "html.parser", multi_valued_attributes=None
            )
            reposContainer = soup.find(id="user-list-repositories")
            if reposContainer:
                repoIndex = 0
                for repo in reposContainer.find_all(
                    "div",
                    class_="col-12 d-block width-full py-4 border-bottom color-border-muted",
                ):
                    if repoIndex >= self.__REPOS_PER_PAGE:
                        logging.error(
                            f"{{__class__}}: {data.page_url} repos count exceed {self.__REPOS_PER_PAGE}"
                        )
                        break
                    repoInfo = RepoInfo()
                    nameBlock = repo.find("div", class_="d-inline-block mb-1")
                    if nameBlock:
                        link = nameBlock.find("a")
                        if link:
                            repoInfo.html_url = "https://github.com" + link.get("href")
                            repoInfo.full_name = link.get("href")[1:]
                            repoInfo.name = repoInfo.full_name.split("/", 1)[1]
                    descBlock = repo.find(
                        "p", "d-inline-block col-9 color-fg-muted pr-4"
                    )
                    if descBlock:
                        repoInfo.description = descBlock.text
                        if repoInfo.description:
                            repoInfo.description = repoInfo.description.strip()
                    infoBlock = repo.find("div", class_="f6 color-fg-muted mt-2")
                    if infoBlock:
                        lanBlock = infoBlock.find(
                            attrs={"itemprop": "programmingLanguage"}
                        )
                        if lanBlock:
                            repoInfo.language = lanBlock.text
                        for linkBlock in infoBlock.find_all("a"):
                            if linkBlock.get("href").endswith("stargazers"):
                                repoInfo.stargazers_count = int(
                                    linkBlock.text.strip().replace(",", "")
                                )
                            elif linkBlock.get("href").endswith("forks"):
                                repoInfo.forks_count = int(
                                    linkBlock.text.strip().replace(",", "")
                                )
                        updateTimeBlock = infoBlock.find("relative-time")
                        if updateTimeBlock:
                            updateTimeStr = updateTimeBlock["datetime"]
                            if updateTimeStr.endswith("Z"):
                                updateTimeStr = updateTimeStr[:-1]
                            repoInfo.pushed_at = datetime.fromisoformat(updateTimeStr)
                    data.listInfo.repos[data.page_first_repo_index + repoIndex] = (
                        repoInfo
                    )
                    repoIndex += 1
                return True
        except Exception as exception:
            if (
                self.__fetchListReposTask_lastExceptionLineNo
                != exception.__traceback__.tb_lineno
                or self.__fetchListReposTask_lastExceptionType != type(exception)
            ):
                self.__fetchListReposTask_lastExceptionLineNo = (
                    exception.__traceback__.tb_lineno
                )
                self.__fetchListReposTask_lastExceptionType = type(exception)
                logging.error(
                    f"{__class__} line {exception.__traceback__.tb_lineno} : {data.page_url} generated an exception: {exception}"
                )
        return False
