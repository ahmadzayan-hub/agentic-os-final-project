import { useI18n } from '../../i18n'
import { Dialog } from './Dialog'

interface ConfirmDialogProps {
  title: string
  message: string
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Confirmation step for destructive actions (clear history, clear memory). */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const { t } = useI18n()
  return (
    <Dialog title={title} onClose={onCancel} labelledById="confirm-title">
      <p className="dialog__body">{message}</p>
      <div className="dialog__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
          {t('common.cancel')}
        </button>
        <button type="button" className="btn btn--danger" onClick={onConfirm} disabled={busy}>
          {busy ? <span className="spinner" aria-hidden="true" /> : null}
          {confirmLabel}
        </button>
      </div>
    </Dialog>
  )
}
