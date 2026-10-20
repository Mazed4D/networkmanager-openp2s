cmake_minimum_required(VERSION 3.22)

project(plasma-nm-openp2s VERSION 0.1.2 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets DBus)
find_package(KF6CoreAddons REQUIRED)
find_package(KF6WidgetsAddons REQUIRED)
find_package(KF6NetworkManagerQt REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBNM REQUIRED IMPORTED_TARGET libnm>=1.30)
find_library(PLASMANM_EDITOR_LIBRARY NAMES plasmanm_editor REQUIRED)

set(NM_OPENP2S_CLI "/usr/bin/nm-openp2s" CACHE STRING "Path of the nm-openp2s command used to import profiles")
if(NOT DEFINED QT6_INSTALL_PLUGINS)
    message(FATAL_ERROR "QT6_INSTALL_PLUGINS is not set; pass -DVPN_PLUGIN_INSTALL_DIR=<qt plugin dir>/plasma/network/vpn")
endif()
set(VPN_PLUGIN_INSTALL_DIR "${QT6_INSTALL_PLUGINS}/plasma/network/vpn" CACHE STRING "Where plasma-nm looks for VPN plugins")

add_library(openp2s_plasma_deps INTERFACE)
target_include_directories(openp2s_plasma_deps INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/compat)
target_compile_definitions(openp2s_plasma_deps INTERFACE QT_NO_KEYWORDS)
target_link_libraries(openp2s_plasma_deps INTERFACE
    Qt6::Widgets
    Qt6::DBus
    KF6::CoreAddons
    KF6::WidgetsAddons
    KF6::NetworkManagerQt
    PkgConfig::LIBNM
    ${PLASMANM_EDITOR_LIBRARY}
)

add_library(plasmanetworkmanagement_openp2sui MODULE
    openp2sui.cpp
    openp2sui.h
    openp2swidget.cpp
    openp2swidget.h
)
set_target_properties(plasmanetworkmanagement_openp2sui PROPERTIES PREFIX "")
target_compile_definitions(plasmanetworkmanagement_openp2sui PRIVATE NM_OPENP2S_CLI="${NM_OPENP2S_CLI}")
target_link_libraries(plasmanetworkmanagement_openp2sui PRIVATE openp2s_plasma_deps)

install(TARGETS plasmanetworkmanagement_openp2sui DESTINATION ${VPN_PLUGIN_INSTALL_DIR})

option(BUILD_TESTING "Build the plugin test" ON)
if(BUILD_TESTING)
    enable_testing()
    add_executable(openp2s-plugin-test tests/plugintest.cpp)
    target_link_libraries(openp2s-plugin-test PRIVATE openp2s_plasma_deps)
    add_test(NAME plugin
        COMMAND openp2s-plugin-test $<TARGET_FILE:plasmanetworkmanagement_openp2sui> ${CMAKE_CURRENT_SOURCE_DIR}/tests/profile.xml)
    set_tests_properties(plugin PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;NM_OPENP2S_CLI=${CMAKE_CURRENT_SOURCE_DIR}/../bin/nm-openp2s")
endif()
