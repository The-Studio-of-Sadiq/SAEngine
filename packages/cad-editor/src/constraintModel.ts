/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { AcDbDatabase, AcDbResultBuffer, AcDbXrecord } from '@mlightcad/data-model';

export type GeomFeature =
	| 'start'
	| 'end'
	| 'mid'
	| 'center'
	| 'radius'
	| 'whole'
	| 'point'
	| 'vertex'
	| 'segment';

export interface GeomRef {
	readonly entityId: string;
	readonly feature: GeomFeature;
	readonly index?: number;
}

export type GeometricConstraintType =
	| 'coincident'
	| 'horizontal'
	| 'vertical'
	| 'parallel'
	| 'perpendicular'
	| 'collinear'
	| 'concentric'
	| 'tangent'
	| 'equal'
	| 'fix'
	| 'symmetric'
	| 'smooth';

export type DimensionalConstraintType =
	| 'aligned'
	| 'linear'
	| 'horizontal'
	| 'vertical'
	| 'angular'
	| 'radial'
	| 'diameter';

export interface GeometricConstraint {
	readonly id: string;
	readonly type: 'geometric';
	readonly kind: GeometricConstraintType;
	readonly refs: readonly GeomRef[];
	readonly symmetryLine?: readonly GeomRef[];
}

export interface DimensionalConstraint {
	readonly id: string;
	readonly type: 'dimensional';
	readonly kind: DimensionalConstraintType;
	readonly refs: readonly GeomRef[];
	readonly name: string;
	readonly expression: string;
	readonly value: number;
	readonly dimensionEntityId?: string;
}

export type ConstraintDefinition = GeometricConstraint | DimensionalConstraint;

export interface ParameterDefinition {
	readonly name: string;
	readonly expression: string;
	readonly value: number;
	readonly isUser?: boolean;
}

export interface ConstraintStore {
	readonly version: 1;
	readonly type: 'SAENGINE_CONSTRAINTS';
	constraints: ConstraintDefinition[];
	parameters: Record<string, ParameterDefinition>;
}

export function createEmptyConstraintStore(): ConstraintStore {
	return {
		version: 1,
		type: 'SAENGINE_CONSTRAINTS',
		constraints: [],
		parameters: {},
	};
}

// ---------------------------------------------------------------------------
// Expression Parser (no eval)
// Supports: numbers, parameters, +, -, *, /, unary -, parentheses ()
// ---------------------------------------------------------------------------

type TokenType = 'NUMBER' | 'IDENT' | 'PLUS' | 'MINUS' | 'MUL' | 'DIV' | 'LPAREN' | 'RPAREN' | 'EOF';

interface Token {
	type: TokenType;
	value?: string | number;
}

function tokenize(input: string): Token[] {
	const tokens: Token[] = [];
	let i = 0;
	while (i < input.length) {
		const ch = input[i];
		if (/\s/.test(ch)) {
			i++;
			continue;
		}
		if (ch === '+') {
			tokens.push({ type: 'PLUS' });
			i++;
		} else if (ch === '-') {
			tokens.push({ type: 'MINUS' });
			i++;
		} else if (ch === '*') {
			tokens.push({ type: 'MUL' });
			i++;
		} else if (ch === '/') {
			tokens.push({ type: 'DIV' });
			i++;
		} else if (ch === '(') {
			tokens.push({ type: 'LPAREN' });
			i++;
		} else if (ch === ')') {
			tokens.push({ type: 'RPAREN' });
			i++;
		} else if (/[0-9.]/.test(ch)) {
			let numStr = '';
			while (i < input.length && /[0-9.]/.test(input[i])) {
				numStr += input[i];
				i++;
			}
			const val = parseFloat(numStr);
			if (isNaN(val)) throw new Error(`Invalid number: "${numStr}"`);
			tokens.push({ type: 'NUMBER', value: val });
		} else if (/[a-zA-Z_]/.test(ch)) {
			let ident = '';
			while (i < input.length && /[a-zA-Z0-9_]/.test(input[i])) {
				ident += input[i];
				i++;
			}
			tokens.push({ type: 'IDENT', value: ident });
		} else {
			throw new Error(`Unexpected character in expression: '${ch}'`);
		}
	}
	tokens.push({ type: 'EOF' });
	return tokens;
}

class Parser {
	private pos = 0;
	constructor(private tokens: Token[], private params: Record<string, number>) {}

	private peek(): Token {
		return this.tokens[this.pos];
	}

	private consume(): Token {
		return this.tokens[this.pos++];
	}

	public parse(): number {
		const val = this.parseExpression();
		if (this.peek().type !== 'EOF') {
			throw new Error(`Unexpected token at end of expression: ${this.peek().type}`);
		}
		return val;
	}

	private parseExpression(): number {
		let left = this.parseTerm();
		while (this.peek().type === 'PLUS' || this.peek().type === 'MINUS') {
			const op = this.consume().type;
			const right = this.parseTerm();
			if (op === 'PLUS') left += right;
			else left -= right;
		}
		return left;
	}

	private parseTerm(): number {
		let left = this.parseFactor();
		while (this.peek().type === 'MUL' || this.peek().type === 'DIV') {
			const op = this.consume().type;
			const right = this.parseFactor();
			if (op === 'MUL') {
				left *= right;
			} else {
				if (Math.abs(right) < 1e-15) throw new Error('Division by zero');
				left /= right;
			}
		}
		return left;
	}

	private parseFactor(): number {
		if (this.peek().type === 'MINUS') {
			this.consume();
			return -this.parseFactor();
		}
		if (this.peek().type === 'PLUS') {
			this.consume();
			return this.parseFactor();
		}
		return this.parsePrimary();
	}

	private parsePrimary(): number {
		const token = this.consume();
		if (token.type === 'NUMBER') {
			return token.value as number;
		}
		if (token.type === 'IDENT') {
			const name = token.value as string;
			if (!(name in this.params)) {
				throw new Error(`Undefined parameter in expression: "${name}"`);
			}
			return this.params[name];
		}
		if (token.type === 'LPAREN') {
			const val = this.parseExpression();
			if (this.peek().type !== 'RPAREN') {
				throw new Error('Missing closing parenthesis \')\'');
			}
			this.consume();
			return val;
		}
		throw new Error(`Unexpected token in expression: ${token.type}`);
	}
}

/** Evaluate an expression string with parameter replacements. */
export function evaluateExpression(expression: string, params: Record<string, number> = {}): number {
	const trimmed = expression.trim();
	if (!trimmed) return 0;
	const tokens = tokenize(trimmed);
	const parser = new Parser(tokens, params);
	return parser.parse();
}

/**
 * Re-evaluate all parameter values in dependency order.
 * Updates parameter values in-place and returns map of name -> value.
 */
export function evaluateAllParameters(params: Record<string, ParameterDefinition>): Record<string, number> {
	const values: Record<string, number> = {};
	const pending = new Set(Object.keys(params));
	const visiting = new Set<string>();

	function resolve(name: string): number {
		if (name in values) return values[name];
		if (visiting.has(name)) {
			throw new Error(`Cyclic dependency detected in parameter "${name}"`);
		}
		visiting.add(name);
		const def = params[name];
		if (!def) {
			throw new Error(`Undefined parameter "${name}"`);
		}
		// Tokenize to find dependencies
		const tokens = tokenize(def.expression);
		for (const t of tokens) {
			if (t.type === 'IDENT') {
				const dep = t.value as string;
				if (dep in params && !(dep in values)) {
					resolve(dep);
				}
			}
		}
		const val = evaluateExpression(def.expression, values);
		values[name] = val;
		visiting.delete(name);
		pending.delete(name);
		return val;
	}

	while (pending.size > 0) {
		const next = pending.values().next().value;
		if (next) resolve(next);
	}

	for (const [k, v] of Object.entries(values)) {
		if (params[k]) {
			(params[k] as { value: number }).value = v;
		}
	}
	return values;
}

// ---------------------------------------------------------------------------
// Database Persistence via AcDbXrecord in db.objects.xrecord
// ---------------------------------------------------------------------------

export const CONSTRAINT_DICTIONARY_KEY = 'SAENGINE_CONSTRAINTS';

/** Saves constraints and parameters to the database resident XRECORD dictionary. */
export function saveConstraintsToDatabase(database: AcDbDatabase, store: ConstraintStore): void {
	if (!database.objects?.xrecord) return;
	const json = JSON.stringify(store);
	const xrec = new AcDbXrecord();
	const buf = new AcDbResultBuffer();
	// Split large JSON payloads into chunks of 250 characters if needed
	const CHUNK_SIZE = 250;
	for (let i = 0; i < json.length; i += CHUNK_SIZE) {
		buf.add({ code: 1, value: json.slice(i, i + CHUNK_SIZE) });
	}
	xrec.data = buf;
	database.objects.xrecord.setAt(CONSTRAINT_DICTIONARY_KEY, xrec);
}

/** Loads constraints and parameters from the database resident XRECORD dictionary. */
export function loadConstraintsFromDatabase(database: AcDbDatabase): ConstraintStore {
	if (!database.objects?.xrecord) return createEmptyConstraintStore();

	// First attempt by key
	let xrec: AcDbXrecord | undefined = database.objects.xrecord.getAt(CONSTRAINT_DICTIONARY_KEY);

	// If not found by key directly, inspect all xrecords for SAENGINE_CONSTRAINTS marker
	if (!xrec) {
		for (const [key, xr] of database.objects.xrecord.entries()) {
			if (key === CONSTRAINT_DICTIONARY_KEY) {
				xrec = xr;
				break;
			}
			const firstVal = xr.data?.at(0)?.value;
			if (typeof firstVal === 'string' && firstVal.includes('SAENGINE_CONSTRAINTS')) {
				xrec = xr;
				break;
			}
		}
	}

	if (!xrec || !xrec.data || xrec.data.length === 0) {
		return createEmptyConstraintStore();
	}

	// Reassemble chunks
	let json = '';
	for (const item of xrec.data) {
		if (typeof item.value === 'string') {
			json += item.value;
		}
	}

	try {
		const parsed = JSON.parse(json);
		if (parsed && parsed.type === 'SAENGINE_CONSTRAINTS') {
			return {
				version: 1,
				type: 'SAENGINE_CONSTRAINTS',
				constraints: Array.isArray(parsed.constraints) ? parsed.constraints : [],
				parameters: parsed.parameters && typeof parsed.parameters === 'object' ? parsed.parameters : {},
			};
		}
	} catch {
		// corrupted or invalid JSON
	}

	return createEmptyConstraintStore();
}
