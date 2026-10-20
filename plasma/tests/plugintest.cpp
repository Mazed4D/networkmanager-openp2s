#include "vpnuiplugin.h"

#include <KPluginFactory>
#include <KPluginMetaData>

#include <QApplication>
#include <QTextStream>

#include <NetworkManager.h>

#include <memory>

namespace
{
const QString ServiceType = QStringLiteral("org.freedesktop.NetworkManager.openp2s");

int fail(const QString &message)
{
    QTextStream(stderr) << "FAIL: " << message << Qt::endl;
    return 1;
}

NMStringMap dataOf(NMSettingVpn *vpn)
{
    NMStringMap map;
    guint length = 0;
    const char **keys = nm_setting_vpn_get_data_keys(vpn, &length);
    for (guint i = 0; i < length; ++i) {
        map.insert(QString::fromUtf8(keys[i]), QString::fromUtf8(nm_setting_vpn_get_data_item(vpn, keys[i])));
    }
    g_free(keys);
    return map;
}

NMStringMap secretsOf(NMSettingVpn *vpn)
{
    NMStringMap map;
    guint length = 0;
    const char **keys = nm_setting_vpn_get_secret_keys(vpn, &length);
    for (guint i = 0; i < length; ++i) {
        map.insert(QString::fromUtf8(keys[i]), QString::fromUtf8(nm_setting_vpn_get_secret(vpn, keys[i])));
    }
    g_free(keys);
    return map;
}
}

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    if (argc < 3) {
        return fail(QStringLiteral("usage: openp2s-plugin-test <plugin.so> <profile.xml>"));
    }

    const KPluginMetaData metaData(QString::fromLocal8Bit(argv[1]));
    if (!metaData.isValid()) {
        return fail(QStringLiteral("no plugin metadata in %1").arg(QString::fromLocal8Bit(argv[1])));
    }
    if (metaData.value(QStringLiteral("X-NetworkManager-Services")) != ServiceType) {
        return fail(QStringLiteral("X-NetworkManager-Services is not %1").arg(ServiceType));
    }

    const auto result = KPluginFactory::instantiatePlugin<VpnUiPlugin>(metaData);
    if (!result) {
        return fail(QStringLiteral("could not instantiate the plugin as a VpnUiPlugin: %1").arg(result.errorText));
    }
    std::unique_ptr<VpnUiPlugin> plugin(result.plugin);

    if (!plugin->supportedFileExtensions().contains(QStringLiteral("*.xml"))) {
        return fail(QStringLiteral("*.xml is not a supported import extension"));
    }

    const auto rejected = plugin->importConnectionSettings(QString::fromLocal8Bit(argv[0]));
    if (rejected || rejected.errorMessage().isEmpty()) {
        return fail(QStringLiteral("importing a non-profile file did not fail with a message"));
    }

    const auto imported = plugin->importConnectionSettings(QString::fromLocal8Bit(argv[2]));
    if (!imported) {
        return fail(QStringLiteral("import failed: %1").arg(imported.errorMessage()));
    }
    NMConnection *connection = imported.connection();
    NMSettingVpn *nmVpn = nm_connection_get_setting_vpn(connection);
    if (!nmVpn || QString::fromUtf8(nm_setting_vpn_get_service_type(nmVpn)) != ServiceType) {
        return fail(QStringLiteral("imported connection is not an openp2s VPN"));
    }

    const NMStringMap data = dataOf(nmVpn);
    const NMStringMap secrets = secretsOf(nmVpn);
    for (const QString &key : {QStringLiteral("gateways"), QStringLiteral("authority"), QStringLiteral("client-id"), QStringLiteral("scope")}) {
        if (data.value(key).isEmpty()) {
            return fail(QStringLiteral("imported connection has no %1").arg(key));
        }
    }
    if (secrets.value(QStringLiteral("tls-auth")).size() != 512) {
        return fail(QStringLiteral("imported connection has no tls-auth secret"));
    }

    NetworkManager::VpnSetting::Ptr setting(new NetworkManager::VpnSetting);
    setting->setInitialized(true);
    setting->setServiceType(ServiceType);
    setting->setTimeout(nm_setting_vpn_get_timeout(nmVpn));
    setting->setData(data);
    setting->setSecrets(secrets);

    std::unique_ptr<SettingWidget> widget(plugin->widget(setting, nullptr));
    if (!widget || !widget->isValid()) {
        return fail(QStringLiteral("the settings page rejected an imported connection"));
    }
    NetworkManager::VpnSetting roundTrip;
    roundTrip.fromMap(widget->setting());
    if (roundTrip.serviceType() != ServiceType || roundTrip.data() != data || roundTrip.secrets() != secrets
        || roundTrip.timeout() != setting->timeout()) {
        return fail(QStringLiteral("the settings page did not round-trip the connection unchanged"));
    }

    NetworkManager::VpnSetting::Ptr empty(new NetworkManager::VpnSetting);
    empty->setServiceType(ServiceType);
    std::unique_ptr<SettingWidget> blank(plugin->widget(empty, nullptr));
    if (blank->isValid()) {
        return fail(QStringLiteral("an empty connection was accepted"));
    }

    std::unique_ptr<SettingWidget> auth(plugin->askUser(setting, {}, nullptr));
    if (!auth) {
        return fail(QStringLiteral("askUser returned nothing"));
    }

    g_object_unref(connection);
    QTextStream(stdout) << "OK: plugin loads, imports, and round-trips settings" << Qt::endl;
    return 0;
}
