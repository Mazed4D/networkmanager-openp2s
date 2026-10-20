#pragma once

#include "plasmanm_editor_export.h"

#include <QMessageBox>
#include <QObject>
#include <QVariant>

#include <NetworkManagerQt/ConnectionSettings>
#include <NetworkManagerQt/GenericTypes>
#include <NetworkManagerQt/VpnSetting>

#include <KPluginFactory>

#include "settingwidget.h"

#include <nm-connection.h>

class PLASMANM_EDITOR_EXPORT VpnUiPlugin : public QObject
{
    Q_OBJECT
public:
    enum ErrorType {
        NoError,
        NotImplemented,
        Error
    };

    explicit VpnUiPlugin(QObject *parent = nullptr, const QVariantList & = QVariantList());
    ~VpnUiPlugin() override;

    virtual SettingWidget *widget(const NetworkManager::VpnSetting::Ptr &setting, QWidget *parent) = 0;
    virtual SettingWidget *askUser(const NetworkManager::VpnSetting::Ptr &setting, const QStringList &hints, QWidget *parent) = 0;

    virtual QString suggestedFileName(const NetworkManager::ConnectionSettings::Ptr &connection) const = 0;
    virtual QStringList supportedFileExtensions() const;

    struct ImportResult {
    private:
        NMConnection *m_connection;
        ErrorType m_error = NoError;
        QString m_errorMessage;

    public:
        operator bool() const;

        QString errorMessage() const;

        NMConnection *connection() const;

        static ImportResult fail(const QString &errorMessage);

        static ImportResult pass(NMConnection *connection);

        static ImportResult notImplemented();
    };

    virtual ImportResult importConnectionSettings(const QString &fileName);

    struct ExportResult {
    private:
        ErrorType m_error = NoError;
        QString m_errorMessage;

    public:
        operator bool() const;

        QString errorMessage() const;

        static ExportResult pass();

        static ExportResult fail(const QString &errorMessage);

        static ExportResult notImplemented();
    };

    virtual ExportResult exportConnectionSettings(const NetworkManager::ConnectionSettings::Ptr &connection, const QString &fileName);

    virtual QMessageBox::StandardButtons suggestedAuthDialogButtons() const;

    static KPluginFactory::Result<VpnUiPlugin> loadPluginForType(QObject *parent, const QString &serviceType);
};
