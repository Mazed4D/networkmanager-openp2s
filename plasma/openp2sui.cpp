#include "openp2sui.h"
#include "openp2swidget.h"

#include <KPluginFactory>

#include <QProcess>

#include <NetworkManager.h>

K_PLUGIN_CLASS_WITH_JSON(OpenP2sUiPlugin, "plasmanetworkmanagement_openp2sui.json")

OpenP2sUiPlugin::OpenP2sUiPlugin(QObject *parent, const QVariantList &args)
    : VpnUiPlugin(parent, args)
{
}

OpenP2sUiPlugin::~OpenP2sUiPlugin() = default;

SettingWidget *OpenP2sUiPlugin::widget(const NetworkManager::VpnSetting::Ptr &setting, QWidget *parent)
{
    return new OpenP2sWidget(setting, parent);
}

SettingWidget *OpenP2sUiPlugin::askUser(const NetworkManager::VpnSetting::Ptr &setting, const QStringList &hints, QWidget *parent)
{
    return new OpenP2sAuthWidget(setting, hints, parent);
}

QString OpenP2sUiPlugin::suggestedFileName(const NetworkManager::ConnectionSettings::Ptr &connection) const
{
    Q_UNUSED(connection);
    return {};
}

QStringList OpenP2sUiPlugin::supportedFileExtensions() const
{
    return {QStringLiteral("*.xml")};
}

VpnUiPlugin::ImportResult OpenP2sUiPlugin::importConnectionSettings(const QString &fileName)
{
    QString program = qEnvironmentVariable("NM_OPENP2S_CLI");
    if (program.isEmpty()) {
        program = QStringLiteral(NM_OPENP2S_CLI);
    }

    QProcess process;
    process.start(program, {QStringLiteral("keyfile"), fileName});
    if (!process.waitForStarted(5000)) {
        return ImportResult::fail(QStringLiteral("Could not run %1. Is networkmanager-openp2s installed?").arg(program));
    }
    if (!process.waitForFinished(30000)) {
        process.kill();
        process.waitForFinished(1000);
        return ImportResult::fail(QStringLiteral("Reading the VPN profile timed out."));
    }
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        QString message = QString::fromUtf8(process.readAllStandardError()).trimmed();
        if (message.startsWith(QLatin1String("error: "))) {
            message = message.mid(7);
        }
        return ImportResult::fail(message.isEmpty() ? QStringLiteral("The VPN profile could not be read.") : message);
    }

    const QByteArray keyfileData = process.readAllStandardOutput();
    GKeyFile *keyFile = g_key_file_new();
    GError *error = nullptr;
    NMConnection *connection = nullptr;
    if (g_key_file_load_from_data(keyFile, keyfileData.constData(), keyfileData.size(), G_KEY_FILE_NONE, &error)) {
        connection = nm_keyfile_read(keyFile, "/", NM_KEYFILE_HANDLER_FLAGS_NONE, nullptr, nullptr, &error);
    }
    g_key_file_unref(keyFile);

    if (!connection) {
        const QString message = error ? QString::fromUtf8(error->message) : QStringLiteral("unknown error");
        g_clear_error(&error);
        return ImportResult::fail(QStringLiteral("The converted connection is not valid: %1").arg(message));
    }
    return ImportResult::pass(connection);
}

QMessageBox::StandardButtons OpenP2sUiPlugin::suggestedAuthDialogButtons() const
{
    return QMessageBox::Close;
}

#include "openp2sui.moc"
