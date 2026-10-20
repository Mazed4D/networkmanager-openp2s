#include "openp2swidget.h"

#include <QFormLayout>
#include <QLabel>
#include <QLineEdit>
#include <QRegularExpression>
#include <QVBoxLayout>

namespace
{
const QString ServiceType = QStringLiteral("org.freedesktop.NetworkManager.openp2s");
const QString KeyGateways = QStringLiteral("gateways");
const QString KeyAuthority = QStringLiteral("authority");
const QString KeyClientId = QStringLiteral("client-id");
const QString KeyScope = QStringLiteral("scope");
const QString KeyUser = QStringLiteral("user");
const QString KeyDnsServers = QStringLiteral("dns-servers");
const QString KeyDnsDomains = QStringLiteral("dns-domains");
const uint DefaultTimeout = 300;

QString toStored(const QString &text)
{
    static const QRegularExpression separators(QStringLiteral("[,;\\s]+"));
    return text.split(separators, Qt::SkipEmptyParts).join(QLatin1Char(','));
}

QString toDisplayed(const QString &stored)
{
    return stored.split(QLatin1Char(','), Qt::SkipEmptyParts).join(QStringLiteral(", "));
}

void put(NMStringMap &data, const QString &key, const QString &value)
{
    if (value.isEmpty()) {
        data.remove(key);
    } else {
        data.insert(key, value);
    }
}

NetworkManager::VpnSetting::Ptr asVpn(const NetworkManager::Setting::Ptr &setting)
{
    return setting.dynamicCast<NetworkManager::VpnSetting>();
}
}

OpenP2sWidget::OpenP2sWidget(const NetworkManager::VpnSetting::Ptr &setting, QWidget *parent, Qt::WindowFlags f)
    : SettingWidget(setting, parent, f)
    , m_setting(setting)
    , m_hint(new QLabel(this))
    , m_gateways(new QLineEdit(this))
    , m_authority(new QLineEdit(this))
    , m_clientId(new QLineEdit(this))
    , m_user(new QLineEdit(this))
    , m_dnsServers(new QLineEdit(this))
    , m_dnsDomains(new QLineEdit(this))
{
    m_hint->setWordWrap(true);
    m_authority->setReadOnly(true);
    m_clientId->setReadOnly(true);
    m_dnsServers->setPlaceholderText(QStringLiteral("10.0.0.4"));
    m_dnsDomains->setPlaceholderText(QStringLiteral("corp.example, privatelink.database.windows.net"));

    auto *dnsNote = new QLabel(QStringLiteral("Names under the DNS domains are resolved through the VPN's DNS servers. "
                                              "To send every lookup through the VPN while connected, add ~. as a search "
                                              "domain on the IPv4 tab."),
                               this);
    dnsNote->setWordWrap(true);

    auto *form = new QFormLayout;
    form->addRow(QStringLiteral("Gateway:"), m_gateways);
    form->addRow(QStringLiteral("Microsoft Entra tenant:"), m_authority);
    form->addRow(QStringLiteral("Application ID:"), m_clientId);
    form->addRow(QStringLiteral("Sign in for local user:"), m_user);
    form->addRow(QStringLiteral("DNS servers:"), m_dnsServers);
    form->addRow(QStringLiteral("DNS domains:"), m_dnsDomains);

    auto *layout = new QVBoxLayout(this);
    layout->addWidget(m_hint);
    layout->addLayout(form);
    layout->addWidget(dnsNote);
    layout->addStretch();

    for (QLineEdit *edit : {m_gateways, m_user, m_dnsServers, m_dnsDomains}) {
        connect(edit, &QLineEdit::textChanged, this, &OpenP2sWidget::slotWidgetChanged);
    }

    watchChangedSetting();
    KAcceleratorManager::manage(this);

    if (setting) {
        loadConfig(setting);
    }
    updateHint();
}

OpenP2sWidget::~OpenP2sWidget() = default;

void OpenP2sWidget::loadConfig(const NetworkManager::Setting::Ptr &setting)
{
    const NetworkManager::VpnSetting::Ptr vpn = asVpn(setting);
    if (!vpn) {
        return;
    }

    m_data = vpn->data();
    m_gateways->setText(toDisplayed(m_data.value(KeyGateways)));
    m_authority->setText(m_data.value(KeyAuthority));
    m_clientId->setText(m_data.value(KeyClientId));
    m_user->setText(m_data.value(KeyUser));
    m_dnsServers->setText(toDisplayed(m_data.value(KeyDnsServers)));
    m_dnsDomains->setText(toDisplayed(m_data.value(KeyDnsDomains)));

    loadSecrets(setting);
    updateHint();
}

void OpenP2sWidget::loadSecrets(const NetworkManager::Setting::Ptr &setting)
{
    const NetworkManager::VpnSetting::Ptr vpn = asVpn(setting);
    if (!vpn) {
        return;
    }

    const NMStringMap secrets = vpn->secrets();
    for (auto it = secrets.cbegin(); it != secrets.cend(); ++it) {
        if (!it.value().isEmpty()) {
            m_secrets.insert(it.key(), it.value());
        }
    }
}

QVariantMap OpenP2sWidget::setting() const
{
    NetworkManager::VpnSetting vpn;
    vpn.setServiceType(ServiceType);
    if (m_setting) {
        vpn.setPersistent(m_setting->persistent());
        vpn.setUsername(m_setting->username());
        vpn.setTimeout(m_setting->timeout() ? m_setting->timeout() : DefaultTimeout);
    } else {
        vpn.setTimeout(DefaultTimeout);
    }

    NMStringMap data = m_data;
    put(data, KeyGateways, toStored(m_gateways->text()));
    put(data, KeyUser, m_user->text().trimmed());
    put(data, KeyDnsServers, toStored(m_dnsServers->text()));
    put(data, KeyDnsDomains, toStored(m_dnsDomains->text()));

    vpn.setData(data);
    vpn.setSecrets(m_secrets);
    return vpn.toMap();
}

bool OpenP2sWidget::isValid() const
{
    return !toStored(m_gateways->text()).isEmpty() && !m_data.value(KeyAuthority).isEmpty() && !m_data.value(KeyClientId).isEmpty()
        && !m_data.value(KeyScope).isEmpty();
}

void OpenP2sWidget::updateHint()
{
    if (m_data.value(KeyAuthority).isEmpty()) {
        m_hint->setText(QStringLiteral("Connections of this type are created from an Azure VPN profile: use Import VPN Connection… "
                                       "and choose the azurevpnconfig.xml file from the Azure portal."));
    } else {
        m_hint->setText(QStringLiteral("You sign in with Microsoft Entra ID in your browser when you connect."));
    }
}

OpenP2sAuthWidget::OpenP2sAuthWidget(const NetworkManager::VpnSetting::Ptr &setting, const QStringList &hints, QWidget *parent)
    : SettingWidget(setting, hints, parent)
    , m_setting(setting)
{
    auto *label = new QLabel(QStringLiteral("This VPN connection is missing the key from its Azure profile. "
                                            "Import the azurevpnconfig.xml profile again to repair it."),
                             this);
    label->setWordWrap(true);
    auto *layout = new QVBoxLayout(this);
    layout->addWidget(label);
}

OpenP2sAuthWidget::~OpenP2sAuthWidget() = default;

QVariantMap OpenP2sAuthWidget::setting() const
{
    NetworkManager::VpnSetting vpn;
    vpn.setServiceType(ServiceType);
    if (m_setting) {
        vpn.setData(m_setting->data());
        vpn.setSecrets(m_setting->secrets());
    }
    return vpn.toMap();
}
