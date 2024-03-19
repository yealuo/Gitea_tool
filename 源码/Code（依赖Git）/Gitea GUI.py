import json
import os
import subprocess
import sys

import git
import requests
from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal, QRunnable, QObject, QThreadPool
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QTreeWidgetItem, QFileDialog, QTreeWidget, \
    QPushButton, QCheckBox, QLineEdit, QTextEdit
from git import remote

'''
Gitea API接口
----------------------------------------------------------
服务器地址
service_url = 'http://localhost:3000'  # 默认地址
登录
login_url = f'{service_url}/api/v1/user'
获取用户的所有仓库
get_repo_url = f'{service_url}/api/v1/user/repos'
获取指定文件的详细信息
get_contents_url = f'{service_url}/api/v1/repos/{repo_owner}/{repo_name}/contents/{file_path}'
----------------------------------------------------------
'''
service_url = None
login_url = None
get_repo_url = None
Username = None
Password = None


# 登录UI
class LoginUI:
    def __init__(self):
        # 成员初始化
        self.login_ui = uic.loadUi("./UI/login.ui")
        icon = QIcon("./UI/gitea.ico")
        self.login_ui.setWindowIcon(icon)
        self.mainUI = None
        self.if_remember: QCheckBox = self.login_ui.if_remember
        self.url: QLineEdit = self.login_ui.url
        self.username_edit: QLineEdit = self.login_ui.username
        self.password_edit: QLineEdit = self.login_ui.password
        self.if_remember.setCheckState(self.get_config())

        # 根据用户选择自动填充服务器地址、账号和密码
        self.auto_fill()

        # 信号连接
        self.username_edit.textChanged.connect(self.password_edit.clear)  # 账号更改时清空密码
        self.if_remember.stateChanged.connect(self.alter_config)  # 更改配置
        self.login_ui.pushButton.clicked.connect(self.login)  # 登录逻辑

    # 打开界面
    def show(self):
        self.login_ui.show()

    # 获取配置
    def get_config(self):
        with open('./data/config.json', 'r') as f:
            data = json.load(f)

        if data['if_remember']:
            return Qt.CheckState.Checked
        elif not data['if_remember']:
            return Qt.CheckState.Unchecked

    def get_config_bool(self):
        with open('./data/config.json', 'r') as f:
            data = json.load(f)

        if data['if_remember']:
            return True
        elif not data['if_remember']:
            return False

    # 更改配置
    def alter_config(self, state: int):
        with open('./data/config.json', 'r') as f:
            data = json.load(f)

        if state == 0:  # 不记住密码
            data['if_remember'] = False

            # 清除密码记录
            with open('./data/login_data', 'r') as f:
                lines = f.readlines()

            if len(lines) > 2:
                del lines[2]
                with open('./data/login_data', 'w') as f:
                    f.writelines(lines)

        elif state == 2:  # 记住密码
            data['if_remember'] = True

        with open('./data/config.json', 'w') as f:
            json.dump(data, f, indent=4)

    # 自动填充
    def auto_fill(self):
        with open('./data/login_data', 'r') as f:
            lines = f.readlines()

        if lines:
            self.url.setText(lines[0].strip())
            if len(lines) > 1:
                self.username_edit.setText(lines[1].strip())
            if self.get_config_bool():
                if len(lines) > 2:
                    self.password_edit.setText(lines[2].strip())

    # 保存服务器地址
    def save_url(self, url):
        with open('./data/login_data', 'r') as f:
            lines = f.readlines()
            if lines:
                lines[0] = url + '\n'
            else:
                lines.append(url + '\n')

        with open('./data/login_data', 'w') as f:
            f.writelines(lines)

    # 保存账号
    def save_username(self, username):
        with open('./data/login_data', 'r') as f:
            lines = f.readlines()
            if len(lines) > 1:
                lines[1] = username + '\n'
            else:
                lines.append(username + '\n')

        with open('./data/login_data', 'w') as f:
            f.writelines(lines)

    # 保存密码
    def save_password(self, password):
        with open('./data/login_data', 'r') as f:
            lines = f.readlines()
            if len(lines) > 2:
                lines[2] = password
            else:
                lines.append(password + '\n')

        with open('./data/login_data', 'w') as f:
            f.writelines(lines)

    # 登录验证逻辑
    def login(self):
        global service_url, login_url, get_repo_url, Username, Password

        service_url = self.url.text()  # 修改服务器地址
        Username = self.username_edit.text()
        Password = self.password_edit.text()

        # Gitea API
        # 登录
        login_url = f'{service_url}/api/v1/user'
        # 获取用户的所有仓库
        get_repo_url = f'{service_url}/api/v1/user/repos'

        try:
            response = requests.get(login_url, auth=(Username, Password))
            if response.status_code == 200:
                # 保存信息
                self.save_url(service_url)
                self.save_username(Username)
                if self.get_config_bool():
                    self.save_password(Password)

                # 窗口逻辑
                self.login_ui.close()  # 关闭当前登录窗口
                self.mainUI = MainUI()  # 打开主窗口

            else:
                QMessageBox.critical(self.login_ui, "登录失败", "用户名或密码错误",
                                     QMessageBox.StandardButton.Retry)
        except requests.exceptions.RequestException as e:
            QMessageBox.critical(self.login_ui, "错误", str(e), QMessageBox.StandardButton.Ok)


# 获取用户仓库线程
class GetReposSignal(QObject):
    get_ready = pyqtSignal(tuple)
    error_signal = pyqtSignal(str)


class GetRepos(QRunnable):
    def __init__(self, url, ui, tree_widget_item):
        super().__init__()
        self.url = url
        self.ui = ui
        self.tree_widget_item = tree_widget_item
        self.signals = GetReposSignal()

    def run(self):
        try:
            # 此api每页最多返回50个结果，因此需要循环获取
            page_num = 1
            while True:
                params = {'page': page_num, 'limit': 50}
                response = requests.get(self.url, auth=(Username, Password), params=params)
                if response.status_code == 200:
                    if len(response.json()) != 0:
                        data = response.json()
                        # 将结果传递出去
                        data_tuple = (data, self.tree_widget_item)
                        self.signals.get_ready.emit(data_tuple)
                        page_num += 1
                    else:  # 页面为空，结果获取结束
                        break
                else:
                    self.signals.error_signal.emit(
                        f'HTTP {str(response.status_code)}\n{self.url}\n\nerrors:{response.json()["errors"]}\nmessage:{response.json()["message"]}')
        except requests.exceptions as e:
            self.signals.error_signal.emit(str(e) + '\n' + self.url)


# 获取仓库文件线程
class GetDataSignal(QObject):
    get_ready = pyqtSignal(tuple)
    error_signal = pyqtSignal(str)


class GetData(QRunnable):
    def __init__(self, url, ui, tree_widget_item):
        super().__init__()
        self.url = url
        self.ui = ui
        self.tree_widget_item = tree_widget_item
        self.signals = GetDataSignal()

    def run(self):
        try:
            response = requests.get(self.url, auth=(Username, Password))
            if response.status_code == 200:
                data = response.json()
                # 将结果传递出去
                data_tuple = (data, self.tree_widget_item)
                self.signals.get_ready.emit(data_tuple)
            else:
                self.signals.error_signal.emit(
                    f'HTTP {str(response.status_code)}\n{self.url}\n\nerrors:{response.json()["errors"]}\nmessage:{response.json()["message"]}')
        except requests.exceptions as e:
            self.signals.error_signal.emit(str(e) + '\n' + self.url)


# 全局函数
# 添加仓库文件或文件夹响应函数
def add_child_call(data_tuple):
    data = data_tuple[0]
    tree_widget_item = data_tuple[1]
    # 向仓库中添加文件或文件夹
    for contents in data:
        if contents['type'] == 'file':  # 如果是文件类型，不可展开
            contents_item = QTreeWidgetItem(tree_widget_item)
            contents_item.setText(0, contents["name"])
            contents_item.setText(1, '文件')
            contents_item.setText(2, str(contents["size"]))
            contents_item.setCheckState(0, Qt.CheckState.Unchecked)  # 文件默认不勾选
            contents_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)  # 文件不可展开

        elif contents['type'] == 'dir':  # 如果是文件夹类型，可以展开
            contents_item = QTreeWidgetItem(tree_widget_item)
            contents_item.setText(0, contents["name"])
            contents_item.setText(1, '文件夹')
            contents_item.setCheckState(0, Qt.CheckState.Unchecked)  # 文件夹默认不勾选
            contents_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)  # 文件夹可以展开


# 获取节点类型
def get_widget_type(widget: QTreeWidgetItem) -> str:
    if widget.childIndicatorPolicy() == QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator:
        return 'dir'
    elif widget.childIndicatorPolicy() == QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator:
        return 'file'


# 获取文件在仓库中的路径
def get_file_path_in_repo(tree_widget_item):
    if tree_widget_item.parent() is not None:
        file_path = tree_widget_item.text(0)  # 获取文件名
        item = tree_widget_item
        while item.parent() is not None and item.parent().parent() is not None:
            item = item.parent()
            file_path = item.text(0) + '/' + file_path
        return file_path

    else:
        return ''


# 获取仓库名
def get_repo_name(tree_widget_item):
    item = tree_widget_item
    while item.parent() is not None:
        item = item.parent()
    return item.text(0)


# 获取仓库拥有者
def get_repo_owner(tree_widget_item):
    item = tree_widget_item
    while item.parent() is not None:
        item = item.parent()
    return item.text(3)


# 获取仓库默认分支
def get_repo_default_branch(tree_widget_item):
    item = tree_widget_item
    while item.parent() is not None:
        item = item.parent()
    return item.text(4)


# 检查父文件夹是否在下载列表中
def is_in_selected_folder(item, download_list):
    current_item = item
    while current_item.parent() is not None:
        if current_item.parent() in download_list:
            return True
        current_item = current_item.parent()
    return False


# 对下载列表去重
def remove_duplicate_item(download_list):
    for tree_widget_item in download_list:
        if is_in_selected_folder(tree_widget_item, download_list):
            download_list.remove(tree_widget_item)


# Git依赖检查
def check_git_installed():
    try:
        # 使用subprocess运行git --version命令
        subprocess.run(["git", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True  # 如果命令成功执行，则Git已安装
    except subprocess.CalledProcessError:
        return False  # 如果命令执行失败，则Git未安装


# 判断仓库是否初始化
def is_repo_initialized(repo_path):
    git_folder = repo_path + '/' + '.git'
    return os.path.exists(git_folder) and os.path.isdir(git_folder)


# 主UI
class MainUI:
    def __init__(self):
        # 导入UI
        self.main_ui = uic.loadUi("./UI/main.ui")
        icon = QIcon("./UI/gitea.ico")
        self.main_ui.setWindowIcon(icon)

        # 定义成员变量
        self.tree_widget: QTreeWidget = self.main_ui.treeWidget
        self.log: QTextEdit = self.main_ui.log_textEdit
        self.push_button: QPushButton = self.main_ui.pushButton
        self.refresh_button: QPushButton = self.main_ui.refresh_button
        self.search_name_edit: QLineEdit = self.main_ui.search_name_edit
        self.save_path = ''
        self.repo_list = []  # 缓存仓库列表
        self.download_list = []  # 下载列表
        # 线程池
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(15)  # 限制最多线程数

        # 调整控件
        self.tree_widget.header().resizeSection(0, 400)
        self.tree_widget.header().resizeSection(1, 100)
        self.tree_widget.header().resizeSection(2, 100)
        self.tree_widget.header().resizeSection(3, 200)
        self.tree_widget.header().resizeSection(4, 100)
        self.log.hide()

        # 主窗口启动
        self.main_ui.show()

        # 添加仓库
        self.add_repo(get_repo_url, self.tree_widget)

        # 信号连接
        self.tree_widget.itemChanged.connect(self.item_changed)  # 节点勾选框状态改变
        self.tree_widget.itemChanged.connect(self.change_download_list)  # 管理下载列表
        self.tree_widget.itemExpanded.connect(self.item_expand)  # 节点被展开
        self.search_name_edit.textChanged.connect(self.search_repo)  # 搜索框内容变化时
        self.refresh_button.clicked.connect(self.refresh_repo)  # 刷新按钮逻辑
        self.push_button.clicked.connect(self.select_download_path)  # 下载按钮逻辑

    # 添加用户仓库
    def add_repo(self, url, tree_widget_item):
        self.repo_list.clear()  # 重新获取仓库时清除缓存
        add_repo_thread = GetRepos(url, self.main_ui, tree_widget_item)
        add_repo_thread.signals.get_ready.connect(self.add_repo_call)
        add_repo_thread.signals.error_signal.connect(self.message_box)
        self.threadpool.start(add_repo_thread)

    # 添加用户仓库线程响应函数
    def add_repo_call(self, data_tuple):
        data = data_tuple[0]
        tree_widget_item = data_tuple[1]
        for repo_info in data:
            repo_name = repo_info['name']
            repo_owner = repo_info['owner']['login']
            branch = repo_info['default_branch']
            repo_item = QTreeWidgetItem(tree_widget_item)
            repo_item.setText(0, repo_name)
            repo_item.setText(1, '仓库')
            repo_item.setText(3, repo_owner)
            repo_item.setText(4, branch)
            repo_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)  # 所有仓库均可展开
            repo_item.setCheckState(0, Qt.CheckState.Unchecked)  # 仓库默认不勾选
            self.repo_list.append(repo_item)  # 将仓库项目缓存

    # 当节点被展开，加载它的子节点
    def item_expand(self, tree_widget_item):
        tree_widget_item.takeChildren()
        repo_name = get_repo_name(tree_widget_item)
        repo_owner = get_repo_owner(tree_widget_item)
        file_path = get_file_path_in_repo(tree_widget_item)
        get_contents_url = f'{service_url}/api/v1/repos/{repo_owner}/{repo_name}/contents/{file_path}'
        self.add_contents(get_contents_url, tree_widget_item)

    # 添加仓库文件或文件夹
    def add_contents(self, url, tree_widget_item):
        add_contents_thread = GetData(url, self.main_ui, tree_widget_item)
        add_contents_thread.signals.get_ready.connect(add_child_call)
        add_contents_thread.signals.error_signal.connect(self.message_box)
        self.threadpool.start(add_contents_thread)

    # 勾选节点时递归勾选子节点
    def check_children(self, tree_widget_item, state):
        for i in range(tree_widget_item.childCount()):
            child = tree_widget_item.child(i)
            child.setCheckState(0, state)
            self.check_children(child, state)

    # 取消勾选节点时递归取消勾选父节点
    def check_parents(self, tree_widget_item, state):
        if state == Qt.CheckState.Checked:
            pass
        else:
            if tree_widget_item.parent() is not None:
                tree_widget_item = tree_widget_item.parent()
                tree_widget_item.setCheckState(0, Qt.CheckState.Unchecked)
                self.check_parents(tree_widget_item, state)
            else:
                pass

    # 当节点勾选状态变化时
    def item_changed(self, tree_widget_item, column):
        self.tree_widget.itemChanged.disconnect(self.item_changed)  # 避免无限递归，断开连接

        if tree_widget_item.childCount() > 0:  # 如果有子节点
            self.check_children(tree_widget_item, tree_widget_item.checkState(column))

        if tree_widget_item.parent() is not None:  # 如果有父节点
            self.check_parents(tree_widget_item, tree_widget_item.checkState(column))

        self.main_ui.treeWidget.itemChanged.connect(self.item_changed)  # 重新连接

    # 管理下载列表，勾选节点则加入，取消勾选则移除
    def change_download_list(self, tree_widget_item, column):
        check_state = tree_widget_item.checkState(column)
        if check_state == Qt.CheckState.Checked:
            self.download_list.append(tree_widget_item)
        else:
            try:
                self.download_list.remove(tree_widget_item)
            except ValueError:
                pass

    # 刷新仓库列表
    def refresh_repo(self):
        self.tree_widget.clear()  # 清空仓库列表
        self.add_repo(get_repo_url, self.tree_widget)

    # 搜索指定仓库
    def search_repo(self, text):
        search_text = text
        if not search_text:
            self.refresh_repo()
            return

        # 隐藏所有仓库
        for item_index in range(self.tree_widget.topLevelItemCount()):
            top_level_item = self.tree_widget.topLevelItem(item_index)
            top_level_item.setHidden(True)

        # 遍历仓库列表，显示与搜索文本匹配的仓库
        for repo_item in self.repo_list:
            if search_text.lower() in repo_item.text(0).lower():
                repo_item.setHidden(False)

    # 选择下载到本地的路径
    def select_download_path(self):
        # 开始下载前检查Git是否可用
        if not check_git_installed():
            QMessageBox.critical(self.main_ui, '错误', '没有检测到Git，请检查Git是否正确安装！',
                                 QMessageBox.StandardButton.Ok)
        else:
            self.save_path = QFileDialog.getExistingDirectory(self.main_ui, "选择下载路径", os.getcwd())
            if self.save_path:
                self.download_selected()

    # 下载选中的文件
    def download_selected(self):
        # 对下载列表去重
        remove_duplicate_item(self.download_list)

        if not self.download_list:  # 如果没有选择
            QMessageBox.warning(self.main_ui, "警告", "请选择要下载的文件", QMessageBox.StandardButton.Ok)

        # 启动下载线程
        self.log.show()
        self.push_button.setEnabled(False)  # 开始下载后禁用按钮
        self.tree_widget.setEnabled(False)  # 开始下载后禁止与文件浏览器交互
        self.progress = Progress()
        self.progress.signals.info_signal.connect(self.update_log)
        download_thread = Download(self.progress, self.download_list, self.save_path)
        download_thread.signals.finish_signal.connect(self.download_finish)
        self.threadpool.start(download_thread)

    # 提示框
    def message_box(self, message):
        QMessageBox.critical(self.main_ui, "错误", str(message), QMessageBox.StandardButton.Ok)

    # 更新日志
    def update_log(self, info):
        self.log.append(f'{info}\n')

    # 下载完成
    def download_finish(self):
        QMessageBox.information(self.main_ui, "成功", '所有文件下载完成！', QMessageBox.StandardButton.Ok)
        self.log.hide()
        self.log.clear()
        # 恢复交互
        self.push_button.setEnabled(True)
        self.tree_widget.setEnabled(True)


# 文件下载线程
# 信号类
class Signals(QObject):
    finish_signal = pyqtSignal()
    info_signal = pyqtSignal(str)


# 下载进度获取
class Progress(remote.RemoteProgress):
    def __init__(self):
        super().__init__()
        self.signals = Signals()

    def update(self, *args):
        self.signals.info_signal.emit(self._cur_line)


class Download(QRunnable):
    def __init__(self, progress, download_list, save_path):
        super().__init__()
        self.signals = Signals()
        self.progress = progress
        self.download_list = download_list
        self.save_path = save_path

    def run(self):
        # 创建本地仓库文件夹
        for widget_item in self.download_list:
            repo_name = get_repo_name(widget_item)
            repo_owner = get_repo_owner(widget_item)
            repo_default_branch = get_repo_default_branch(widget_item)
            local_repo_path = f'{self.save_path}/{repo_name}'
            remote_repo_url = f'{service_url}/{repo_owner}/{repo_name}.git'
            config_file_path = f'{local_repo_path}/.git/info/sparse-checkout'
            os.makedirs(local_repo_path, exist_ok=True)  # 确保仓库文件夹存在
            file_path_in_repo = get_file_path_in_repo(widget_item)
            if not file_path_in_repo:  # 如果这个文件夹是仓库
                file_path_in_repo = '*'
            else:
                file_path_in_repo = f'/{file_path_in_repo}'  # 从根目录开始匹配，以防错误

            # git操作
            repo = None
            # 如果没初始化就初始化
            if not is_repo_initialized(local_repo_path):
                repo = git.Repo.init(local_repo_path)
                repo.create_remote(name='origin', url=remote_repo_url)  # 设置远程仓库
                repo.config_writer().set_value("core", "sparseCheckout", "true").release()  # 启用sparse-checkout功能
            else:
                repo = git.Repo(local_repo_path)

            # 向配置文件写入要下载的文件
            with open(config_file_path, 'a', encoding='utf-8') as f:
                f.write(f'{file_path_in_repo}\n')

            # 拉取到工作区
            repo.remote().pull(f'{repo_default_branch}:master',
                               progress=self.progress)  # 从远程仓库的默认分支拉取到本地master分支（本地默认分支为master）
            repo.git.reset('--hard', repo.head.commit)

        self.signals.finish_signal.emit()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 登录界面
    loginUI = LoginUI()
    loginUI.show()

    sys.exit(app.exec())
