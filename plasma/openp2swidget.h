#pragma once

#include "settingwidget.h"

#include <NetworkManagerQt/GenericTypes>
#include <NetworkManagerQt/VpnSetting>

class QLabel;
class QLineEdit;

class OpenP2sWidget : public SettingWidget
{
    Q_OBJECT
public:
    explicit OpenP2sWidget(const NetworkManager::VpnSetting::Ptr &setting, QWidget *parent = nullptr, Qt::WindowFlags f = {});
    ~OpenP2sWidget() override;

    void loadConfig(const NetworkManager::Setting::Ptr &setting) override;
    void loadSecrets(const NetworkManager::Setting::Ptr &setting) override;

    QVariantMap setting() const override;

    bool isValid() const override;

private:
    void updateHint();

    NetworkManager::VpnSetting::Ptr m_setting;
    NMStringMap m_data;
    NMStringMap m_secrets;
    QLabel *m_hint;
    QLineEdit *m_gateways;
    QLineEdit *m_authority;
    QLineEdit *m_clientId;
    QLineEdit *m_user;
    QLineEdit *m_dnsServers;
    QLineEdit *m_dnsDomains;
};

class OpenP2sAuthWidget : public SettingWidget
{
    Q_OBJECT
public:
    OpenP2sAuthWidget(const NetworkManager::VpnSetting::Ptr &setting, const QStringList &hints, QWidget *parent = nullptr);
    ~OpenP2sAuthWidget() override;

    QVariantMap setting() const override;

private:
    NetworkManager::VpnSetting::Ptr m_setting;
};
