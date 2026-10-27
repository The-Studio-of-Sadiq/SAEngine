/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { language } from '../../../../base/common/platform.js';

/**
 * The one place SAEngine turns numbers and dates into text. Engineering numbers (loads, counts,
 * sizes) always use ASCII digits and "." as the decimal point, whatever the UI or system locale:
 * a Bengali ৪ (four) reads as 8. Dates follow the UI language for month names, but keep ASCII
 * digits for the same reason. Never call toLocaleString or Intl without a locale in saengine code.
 */

const NUMBER_LOCALE = 'en-US';

export interface INumberFormatOptions {
	/** Exact number of decimals; sets both bounds below. */
	readonly decimals?: number;
	readonly minDecimals?: number;
	/** Default 0, so 1234.5 → "1,235". */
	readonly maxDecimals?: number;
	/** Thousands separators; default true. */
	readonly grouping?: boolean;
}

const numberFormats = new Map<string, Intl.NumberFormat>();

/** 1234.5 → "1,235"; `{ decimals: 1 }` → "1,234.5". ASCII digits in every locale. */
export function formatNumber(value: number, options: INumberFormatOptions = {}): string {
	const max = options.decimals ?? options.maxDecimals ?? 0;
	const min = Math.min(options.decimals ?? options.minDecimals ?? 0, max);
	const grouping = options.grouping ?? true;
	const key = `${min}/${max}/${grouping}`;
	let format = numberFormats.get(key);
	if (!format) {
		format = new Intl.NumberFormat(NUMBER_LOCALE, { minimumFractionDigits: min, maximumFractionDigits: max, useGrouping: grouping, numberingSystem: 'latn' });
		numberFormats.set(key, format);
	}
	return format.format(value);
}

const dateFormats = new Map<string, Intl.DateTimeFormat>();

/**
 * A date or time in the UI language (`locale`, for tests) with ASCII digits, e.g.
 * `{ day: 'numeric', month: 'short' }` → "27 Oct".
 */
export function formatDate(time: number | Date, options: Intl.DateTimeFormatOptions, locale: string = language): string {
	const key = `${locale}|${JSON.stringify(options)}`;
	let format = dateFormats.get(key);
	if (!format) {
		try {
			format = new Intl.DateTimeFormat(locale, { ...options, numberingSystem: 'latn' });
		} catch {
			format = new Intl.DateTimeFormat(NUMBER_LOCALE, { ...options, numberingSystem: 'latn' });
		}
		dateFormats.set(key, format);
	}
	return format.format(time);
}

/** A date and time, as Date.toLocaleString gives it ("27 Oct 2026, 14:05:09"). */
export const DATE_TIME: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };

/** A clock time, as Date.toLocaleTimeString gives it. */
export const TIME: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit' };
