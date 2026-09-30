import { describe, expect, it } from 'vitest'
import { parseListMap, parseNumberMap } from './cpu'

describe('cpu what-if form parsing', () => {
  it('parses task=cluster lists and numeric maps', () => {
    expect(parseListMap('eis=MID_LF, MID_HF; post_irta=MID_HF\nbad')).toEqual({ eis: ['MID_LF', 'MID_HF'], post_irta: ['MID_HF'] })
    expect(parseNumberMap('eis=6; x=abc; post_irta=8.5')).toEqual({ eis: 6, post_irta: 8.5 })
  })
})
