/** Model cards (ADR 0033): the verdict first — does the model beat the
 *  plain baseline it was tested against? — then the metric for both, what
 *  it predicts, from what, and how it was tested. */
import { usePack } from '../../i18n/pack'
import { modelMessages, type ModelKey } from './messages'
import type { ModelCard } from '../../shared/types'
import './models.css'

const MAX_INPUTS = 6

export function ModelCards({ models, language }: { models: ModelCard[]; language: 'en' | 'ar' }) {
  const { t, formatNumber } = usePack(modelMessages)
  if (!models.length) return null
  const value = (card: ModelCard, number: number) =>
    card.metric.name === 'balanced_accuracy'
      ? formatNumber(number, { style: 'percent', maximumFractionDigits: 1 })
      : formatNumber(number, { maximumFractionDigits: 2 })
  const percent = (number: number) => formatNumber(number, { style: 'percent', maximumFractionDigits: 0 })
  // Clustering predicts nothing, so its verdict is whether groups exist;
  // its improvement is the share of the spread the groups explain.
  const verdict = (card: ModelCard) => {
    if (card.kind === 'clustering') {
      return card.beats_baseline
        ? t('models.groups', { n: formatNumber(Number(card.details.groups ?? 0)), pct: percent(card.improvement) })
        : t('models.noGroups')
    }
    return card.beats_baseline ? t('models.beats', { pct: percent(card.improvement) }) : t('models.weak')
  }
  return (
    <section className="card" aria-labelledby="models-title">
      <h3 className="card__title" id="models-title">{t('models.title')}</h3>
      <p className="field__help">{t('models.help')}</p>
      <div className="finding-grid">
        {models.map((card) => {
          const shown = card.inputs.slice(0, MAX_INPUTS)
          const split =
            card.split.kind === 'time'
              ? t('models.split.time', { first: card.split.first_held_out ?? '' })
              : t(`models.split.${card.split.kind}` as ModelKey)
          return (
            <article className="finding-card" key={card.role}>
              <p className="eyebrow" dir="auto" lang={language}>{card.title.split(' — ')[0].split(': ')[0]}</p>
              <p className={`model-verdict ${card.beats_baseline ? 'model-verdict--beats' : 'model-verdict--weak'}`}>
                {verdict(card)}
              </p>
              <dl className="model-facts">
                <div>
                  <dt>{t(`models.metric.${card.metric.name}` as ModelKey)}</dt>
                  <dd>
                    {t('models.versus', {
                      model: value(card, card.metric.model),
                      baseline: value(card, card.metric.baseline),
                      name: t(`models.baseline.${card.metric.baseline_name}` as ModelKey),
                    })}
                  </dd>
                </div>
                {card.kind === 'clustering' ? null : (
                  <div>
                    <dt>{t('models.target')}</dt>
                    <dd dir="auto">{card.target}</dd>
                  </div>
                )}
                <div>
                  <dt>{card.kind === 'clustering' ? t('models.groupedOn') : t('models.inputs')}</dt>
                  <dd dir="auto">
                    {shown.join(', ')}
                    {card.inputs.length > shown.length ? ` ${t('models.more', { n: formatNumber(card.inputs.length - shown.length) })}` : ''}
                  </dd>
                </div>
                <div>
                  <dt>{t('models.tested')}</dt>
                  <dd>
                    {split} ·{' '}
                    {card.split.kind === 'none'
                      ? t('models.used', { n: formatNumber(card.train_records) })
                      : t('models.records', { train: formatNumber(card.train_records), test: formatNumber(card.test_records) })}
                  </dd>
                </div>
              </dl>
            </article>
          )
        })}
      </div>
    </section>
  )
}
