import { useI18n } from '../../i18n'
import type { MessageKey } from '../../i18n'
import { Dialog } from '../../shared/components/Dialog'
import { Icon } from '../../shared/components/Icon'
import type { IconName } from '../../shared/components/Icon'

const POINTS: Array<{ icon: IconName; text: MessageKey }> = [
  { icon: 'chat', text: 'onboard.p1' },
  { icon: 'command', text: 'onboard.p2' },
  { icon: 'settings', text: 'onboard.p3' },
  { icon: 'memory', text: 'onboard.p4' },
]

interface OnboardingProps {
  onDismiss: () => void
}

/** Short, optional first-run introduction. Shown once; dismissible forever. */
export function Onboarding({ onDismiss }: OnboardingProps) {
  const { t } = useI18n()
  return (
    <Dialog title={t('onboard.title')} onClose={onDismiss} labelledById="onboarding-title">
      <p className="dialog__body">{t('onboard.intro')}</p>
      <ul className="onboard__list">
        {POINTS.map((point) => (
          <li key={point.text} className="onboard__item">
            <span className="onboard__icon">
              <Icon name={point.icon} size={18} />
            </span>
            <span>{t(point.text)}</span>
          </li>
        ))}
      </ul>
      <div className="dialog__actions">
        <button type="button" className="btn btn--primary" onClick={onDismiss}>
          {t('onboard.start')}
        </button>
      </div>
    </Dialog>
  )
}
