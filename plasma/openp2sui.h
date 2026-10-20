#pragma once

#include "vpnuiplugin.h"

class OpenP2sUiPlugin : public VpnUiPlugin
{
    Q_OBJECT
public:
    explicit OpenP2sUiPlugin(QObject *parent = nullptr, const QVariantList &args = QVariantList());
    ~OpenP2sUiPlugin() override;

    SettingWidget *widget(const NetworkManager::VpnSetting::Ptr &setting, QWidget *parent) override;
    SettingWidget *askUser(const NetworkManager::VpnSetting::Ptr &setting, const QStringList &hints, QWidget *parent) override;

    QString suggestedFileName(const NetworkManager::ConnectionSettings::Ptr &connection) const override;
    QStringList supportedFileExtensions() const override;
    ImportResult importConnectionSettings(const QString &fileName) override;

    QMessageBox::StandardButtons suggestedAuthDialogButtons() const override;
};
