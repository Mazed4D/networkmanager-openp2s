#pragma once

#include "plasmanm_editor_export.h"

#include <NetworkManagerQt/Setting>
#include <QWidget>

#include <KAcceleratorManager>

class PLASMANM_EDITOR_EXPORT SettingWidget : public QWidget
{
    Q_OBJECT
public:
    class EnumPasswordStorageType
    {
    public:
        enum PasswordStorageType {
            Store = 0,
            AlwaysAsk,
            NotRequired
        };
    };

    explicit SettingWidget(const NetworkManager::Setting::Ptr &setting = NetworkManager::Setting::Ptr(), QWidget *parent = nullptr, Qt::WindowFlags f = {});
    explicit SettingWidget(const NetworkManager::Setting::Ptr &setting, const QStringList &hints, QWidget *parent = nullptr, Qt::WindowFlags f = {});

    ~SettingWidget() override;

    virtual void loadConfig(const NetworkManager::Setting::Ptr &setting);
    virtual void loadSecrets(const NetworkManager::Setting::Ptr &setting);

    virtual QVariantMap setting() const = 0;

    void watchChangedSetting();

    QString type() const;

    virtual bool isValid() const
    {
        return true;
    }

protected Q_SLOTS:
    void slotWidgetChanged();

Q_SIGNALS:
    void validChanged(bool isValid);
    void settingChanged();

protected:
    QStringList m_hints;

private:
    QString m_type;
};
