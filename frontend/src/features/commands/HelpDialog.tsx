import { useI18n } from '../../i18n'
import { Dialog } from '../../shared/components/Dialog'
import type { CommandInfo } from '../../shared/types'

interface HelpDialogProps {
  commands: CommandInfo[]
  onClose: () => void
}

export function HelpDialog({ commands, onClose }: HelpDialogProps) {
  const { t, tx } = useI18n()
  return (
    <Dialog title={t('help.title')} onClose={onClose} wide labelledById="help-title">
      <p className="dialog__body">
        {tx('help.body', {
          shortcut: (
            <>
              <kbd>Ctrl</kbd>+<kbd>K</kbd>
            </>
          ),
        })}
      </p>
      <table className="cmdtable">
        <thead>
          <tr>
            <th scope="col">{t('help.command')}</th>
            <th scope="col">{t('help.what')}</th>
          </tr>
        </thead>
        <tbody>
          {commands.map((command) => (
            <tr key={command.command}>
              <td>
                {/* A command is typed as written: always left-to-right. */}
                <code dir="ltr">{command.usage}</code>
              </td>
              <td dir="auto">{command.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="dialog__actions">
        <button type="button" className="btn btn--ghost" onClick={onClose}>
          {t('common.close')}
        </button>
      </div>
    </Dialog>
  )
}
