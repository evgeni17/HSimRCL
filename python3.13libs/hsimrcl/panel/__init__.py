# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Браузер SimReady Central для Houdini — Python Panel на Qt (вкладка панели или плавающее окно).

Логика каталога, фильтров, сортировки и фоновых задач — в ядре SimRCL (hsimrcl.core); здесь только виджеты
и связка событий. hou импортируется лишь там, где нода добавляется в сцену.
"""
