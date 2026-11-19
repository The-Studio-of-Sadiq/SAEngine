/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

export enum LinearUnits {
	Scientific = 1,
	Decimal = 2,
	Engineering = 3,
	Architectural = 4,
	Fractional = 5,
}

export enum AngularUnits {
	DecimalDegrees = 0,
	DegMinSec = 1,
	Grads = 2,
	Radians = 3,
	Surveyors = 4,
}

function gcd(a: number, b: number): number {
	let x = Math.abs(a);
	let y = Math.abs(b);
	while (y) {
		const t = y;
		y = x % y;
		x = t;
	}
	return x;
}

export function formatLength(value: number, lunits = 2, luprec = 2): string {
	if (!Number.isFinite(value)) return '0';
	const sign = value < 0 ? '-' : '';
	const abs = Math.abs(value);

	switch (lunits) {
		case LinearUnits.Scientific: {
			const expStr = abs.toExponential(luprec).toUpperCase();
			return sign + expStr.replace(/E([+-])(\d)$/, 'E$10$2');
		}
		case LinearUnits.Engineering: {
			// Feet and decimal inches
			const feet = Math.floor(abs / 12);
			const inches = abs - feet * 12;
			return `${sign}${feet}'-${inches.toFixed(luprec)}"`;
		}
		case LinearUnits.Architectural: {
			// Feet and fractional inches
			const totalInches = abs;
			let feet = Math.floor(totalInches / 12);
			let remInches = totalInches - feet * 12;
			let wholeInches = Math.floor(remInches);
			const frac = remInches - wholeInches;
			const denom = Math.pow(2, Math.max(0, Math.min(8, luprec)));
			let num = Math.round(frac * denom);

			if (num === denom) {
				wholeInches += 1;
				num = 0;
			}
			if (wholeInches === 12) {
				feet += 1;
				wholeInches = 0;
			}

			let inchesPart: string;
			if (num > 0) {
				const g = gcd(num, denom);
				const redNum = num / g;
				const redDen = denom / g;
				inchesPart = wholeInches > 0 ? `${wholeInches} ${redNum}/${redDen}"` : `${redNum}/${redDen}"`;
			} else {
				inchesPart = `${wholeInches}"`;
			}

			return `${sign}${feet}'-${inchesPart}`;
		}
		case LinearUnits.Fractional: {
			let whole = Math.floor(abs);
			const frac = abs - whole;
			const denom = Math.pow(2, Math.max(0, Math.min(8, luprec)));
			let num = Math.round(frac * denom);
			if (num === denom) {
				whole += 1;
				num = 0;
			}
			if (num > 0) {
				const g = gcd(num, denom);
				const redNum = num / g;
				const redDen = denom / g;
				return whole > 0 ? `${sign}${whole} ${redNum}/${redDen}` : `${sign}${redNum}/${redDen}`;
			}
			return `${sign}${whole}`;
		}
		case LinearUnits.Decimal:
		default:
			return sign + abs.toFixed(luprec);
	}
}

export function formatAngle(
	rad: number,
	aunits = 0,
	auprec = 0,
	angbase = 0,
	angdir = 0,
): string {
	// Adjust for angbase and angdir
	let ang = angdir === 1 ? angbase - rad : rad - angbase;
	ang = ((ang % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);

	switch (aunits) {
		case AngularUnits.DegMinSec: {
			const deg = ang * 180 / Math.PI;
			const d = Math.floor(deg);
			const minFloat = (deg - d) * 60;
			const m = Math.floor(minFloat);
			const secFloat = (minFloat - m) * 60;
			const secText = Number(secFloat.toFixed(auprec)).toString();
			return `${d}d${m}'${secText}"`;
		}
		case AngularUnits.Grads: {
			const grads = ang * 200 / Math.PI;
			return `${grads.toFixed(auprec)}g`;
		}
		case AngularUnits.Radians: {
			return `${ang.toFixed(auprec)}r`;
		}
		case AngularUnits.Surveyors: {
			const deg = ((ang * 180 / Math.PI) % 360 + 360) % 360;
			let prefix = 'N';
			let suffix = 'E';
			let deflection = 0;

			if (deg <= 90) {
				prefix = 'N';
				suffix = 'E';
				deflection = 90 - deg;
			} else if (deg <= 180) {
				prefix = 'N';
				suffix = 'W';
				deflection = deg - 90;
			} else if (deg <= 270) {
				prefix = 'S';
				suffix = 'W';
				deflection = 270 - deg;
			} else {
				prefix = 'S';
				suffix = 'E';
				deflection = deg - 270;
			}

			const d = Math.floor(deflection);
			const minFloat = (deflection - d) * 60;
			const m = Math.floor(minFloat);
			const sec = Math.round((minFloat - m) * 60);

			let defStr: string;
			if (sec === 0 && m === 0) {
				defStr = `${d}d`;
			} else if (sec === 0) {
				defStr = `${d}d${m}'`;
			} else {
				defStr = `${d}d${m}'${sec}"`;
			}
			return `${prefix} ${defStr} ${suffix}`;
		}
		case AngularUnits.DecimalDegrees:
		default: {
			const deg = ang * 180 / Math.PI;
			return deg.toFixed(auprec);
		}
	}
}
