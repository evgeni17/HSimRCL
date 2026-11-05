# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Фильтры слева: категории, производители, лицензия, профиль, масса, число тел, размеры по осям.

Выбор хранится в словаре selection ядра (simready_catalog.empty_selection); сайдбар только меняет его
функциями ядра и сообщает об изменении сигналом changed. Поля сервиса строит simready_catalog.search_fields.
"""
from PySide6 import QtCore, QtWidgets

from ..core import simready_catalog as cat
from ..core import simready_dims as dims

KEY_ROLE = QtCore.Qt.UserRole + 1


class Section(QtWidgets.QWidget):
    """Сворачиваемый раздел: кнопка-заголовок и содержимое."""

    def __init__(self, title, content, opened=True, parent=None):
        super().__init__(parent)
        self.button = QtWidgets.QToolButton(text=title, checkable=True, checked=opened)
        self.button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.button.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.button.setArrowType(QtCore.Qt.DownArrow if opened else QtCore.Qt.RightArrow)
        self.content = content
        content.setVisible(opened)
        self.button.toggled.connect(self._toggle)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(self.button)
        layout.addWidget(content)

    def _toggle(self, opened):
        self.button.setArrowType(QtCore.Qt.DownArrow if opened else QtCore.Qt.RightArrow)
        self.content.setVisible(opened)


def _checkable_tree():
    tree = QtWidgets.QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setMinimumHeight(180)
    tree.setUniformRowHeights(True)
    return tree


class Sidebar(QtWidgets.QWidget):
    """Панель фильтров; changed() — выбор изменился (selection уже обновлён)."""

    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.catalog = None
        self.selection = cat.empty_selection()
        self.only_downloaded = False
        self._sync = False   # True, пока заполняем виджеты из selection — сигналы виджетов игнорируем
        inner = QtWidgets.QWidget()
        self.box = QtWidgets.QVBoxLayout(inner)
        self.box.setContentsMargins(4, 4, 4, 4)
        scroll = QtWidgets.QScrollArea(widgetResizable=True)
        scroll.setWidget(inner)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.downloaded = QtWidgets.QCheckBox("Downloaded only")
        self.downloaded.toggled.connect(self._downloaded)
        self.box.addWidget(self.downloaded)
        self.categories = _checkable_tree()
        self.providers = _checkable_tree()
        for tree in (self.categories, self.providers):
            tree.itemChanged.connect(self._tree_changed)
        self.licenses = QtWidgets.QListWidget()
        self.profiles = QtWidgets.QListWidget()
        for listing, field in ((self.licenses, "licenses"), (self.profiles, "profiles")):
            listing.setMaximumHeight(120)
            listing.itemChanged.connect(lambda item, f=field: self._list_changed(f, item))
        self.mass = QtWidgets.QComboBox()
        self.rigid = QtWidgets.QComboBox()
        self.mass.currentIndexChanged.connect(lambda _: self._choice("mass", self.mass))
        self.rigid.currentIndexChanged.connect(lambda _: self._choice("rigid", self.rigid))
        self.size_fields = self._size_grid()
        for title, widget, opened in (("Categories", self.categories, True), ("Providers", self.providers, False),
                                      ("License", self.licenses, False), ("Profile", self.profiles, False),
                                      ("Mass", self.mass, False), ("Bodies", self.rigid, False),
                                      ("Size, m", self.size_fields[0], False)):
            self.box.addWidget(Section(title, widget, opened))
        self.box.addStretch(1)

    # ------------------------------------------------------------ построение из каталога

    def set_catalog(self, catalog):
        """Заполнить разделы из каталога (один раз после загрузки)."""
        self.catalog = catalog
        self._sync = True
        hidden = cat.provider_branch_keys(catalog.tree)
        self.categories.clear()
        self._fill_tree(self.categories.invisibleRootItem(), catalog.tree, hidden, 1)
        self.providers.clear()
        for heading, count, members in cat.provider_groups(cat.provider_list(catalog)):
            parent = self.providers.invisibleRootItem()
            if heading:
                parent = QtWidgets.QTreeWidgetItem(self.providers, ["%s (%s)" % (heading, cat.format_count(count))])
                parent.setFlags(QtCore.Qt.ItemIsEnabled)
                parent.setExpanded(True)
            for provider in members:
                self._check_item(QtWidgets.QTreeWidgetItem(parent, ["%s (%s)" % (provider.name, cat.format_count(provider.count))]),
                                 provider.key)
        self._fill_list(self.licenses, cat.license_options(catalog.stats))
        self._fill_list(self.profiles, cat.profile_options(catalog.stats))
        self._fill_combo(self.mass, cat.mass_options(catalog.stats))
        self._fill_combo(self.rigid, cat.rigid_options(catalog.stats))
        self._sync = False

    def _check_item(self, item, key):
        item.setData(0, KEY_ROLE, key)
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(0, QtCore.Qt.Unchecked)
        return item

    def _fill_tree(self, parent, node, hidden, level):
        """Дерево категорий без ветвей производителей (они в своём разделе)."""
        for child in node.children:
            if level == 1 and child.key in hidden:
                continue
            item = self._check_item(QtWidgets.QTreeWidgetItem(parent, ["%s (%s)" % (child.label, cat.format_count(child.count))]),
                                    child.key)
            self._fill_tree(item, child, hidden, level + 1)

    def _fill_list(self, listing, options):
        listing.clear()
        for option in options:
            item = QtWidgets.QListWidgetItem("%s (%s)" % (option.label, cat.format_count(option.count)))
            item.setData(KEY_ROLE, option.key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            listing.addItem(item)

    def _fill_combo(self, combo, options):
        combo.clear()
        combo.addItem("Any", None)
        for option in options:
            combo.addItem("%s (%s)" % (option.label, cat.format_count(option.count)), option.key)

    def _size_grid(self):
        """Строки X/Y/Z: минимум и максимум в метрах (пусто — без ограничения), как на сайте каталога."""
        widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(widget)
        grid.setContentsMargins(0, 0, 0, 0)
        fields = []
        for row, axis in enumerate(dims.AXES):
            low, high = QtWidgets.QLineEdit(placeholderText="min"), QtWidgets.QLineEdit(placeholderText="max")
            for side, edit in (("min", low), ("max", high)):
                edit.editingFinished.connect(lambda r=row, s=side: self._size_edited(r, s))
            grid.addWidget(QtWidgets.QLabel(axis.upper()), row, 0)
            grid.addWidget(low, row, 1)
            grid.addWidget(high, row, 2)
            fields.append((low, high))
        return widget, fields

    # ------------------------------------------------------------ изменения пользователем

    def _emit(self):
        if not self._sync:
            self.changed.emit()

    def _downloaded(self, on):
        self.only_downloaded = on
        self._emit()

    def _tree_changed(self, item, column):
        key = item.data(0, KEY_ROLE)
        if self._sync or key is None:
            return
        on = item.checkState(0) == QtCore.Qt.Checked
        if on != (key in self.selection["nodes"]):
            self.selection = cat.toggle_member(self.selection, "nodes", key)
            self._emit()

    def _list_changed(self, field, item):
        key = item.data(KEY_ROLE)
        if self._sync or key is None:
            return
        on = item.checkState() == QtCore.Qt.Checked
        if on != (key in self.selection[field]):
            self.selection = cat.toggle_member(self.selection, field, key)
            self._emit()

    def _choice(self, field, combo):
        if self._sync:
            return
        self.selection = dict(self.selection, **{field: combo.currentData()})
        self._emit()

    def _size_edited(self, axis, side):
        low_edit, high_edit = self.size_fields[1][axis]
        try:
            low, high = dims.parse(low_edit.text()), dims.parse(high_edit.text())
        except ValueError:
            return
        low, high = dims.clamp(low, high, side)
        if (low, high) != self.selection["dims"][axis]:
            self.selection = cat.set_dimension(self.selection, axis, (low, high))
            self._refill_sizes()
            self._emit()

    # ------------------------------------------------------------ снятие фильтра из «чипов»

    def remove(self, field, key):
        """Убрать один фильтр (клик по чипу) и привести виджеты в соответствие."""
        if field == "downloaded":
            self.downloaded.setChecked(False)
            return
        if field in ("nodes", "profiles", "licenses"):
            self.selection = cat.toggle_member(self.selection, field, key)
        elif field in ("mass", "rigid"):
            self.selection = dict(self.selection, **{field: None})
        elif field == "dims":
            self.selection = cat.set_dimension(self.selection, key, dims.NO_LIMIT)
        self.refill()
        self._emit()

    def clear(self):
        self.selection = cat.empty_selection()
        self._sync = True
        self.downloaded.setChecked(False)
        self.only_downloaded = False
        self._sync = False
        self.refill()
        self._emit()

    def refill(self):
        """Поставить галочки и поля по текущему selection, не порождая сигналов."""
        self._sync = True
        for tree in (self.categories, self.providers):
            iterator = QtWidgets.QTreeWidgetItemIterator(tree)
            while iterator.value():
                item = iterator.value()
                key = item.data(0, KEY_ROLE)
                if key is not None:
                    item.setCheckState(0, QtCore.Qt.Checked if key in self.selection["nodes"] else QtCore.Qt.Unchecked)
                iterator += 1
        for listing, field in ((self.licenses, "licenses"), (self.profiles, "profiles")):
            for row in range(listing.count()):
                item = listing.item(row)
                item.setCheckState(QtCore.Qt.Checked if item.data(KEY_ROLE) in self.selection[field] else QtCore.Qt.Unchecked)
        for combo, field in ((self.mass, "mass"), (self.rigid, "rigid")):
            value = self.selection[field]
            combo.setCurrentIndex(0 if value is None else max(0, combo.findData(value)))
        self._refill_sizes()
        self._sync = False

    def _refill_sizes(self):
        for (low_edit, high_edit), (low, high) in zip(self.size_fields[1], self.selection["dims"]):
            low_edit.setText(dims.text(low))
            high_edit.setText(dims.text(high))
