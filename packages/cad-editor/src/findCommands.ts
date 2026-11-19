/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import {
	AcDbAttribute,
	AcDbAttributeDefinition,
	AcDbBlockReference,
	AcDbDatabase,
	AcDbDimension,
	AcDbEntity,
	AcDbMLeader,
	AcDbMText,
	AcDbTable,
	AcDbText,
} from '@mlightcad/data-model';
import { CadCommandContext, registerCommand } from './commands.js';

export interface FindOptions {
	readonly matchCase?: boolean;
	readonly wholeWord?: boolean;
	readonly wildcards?: boolean;
	readonly replaceText?: string;
}

export interface FindMatch {
	readonly entity: AcDbEntity;
	readonly entityId: string;
	readonly type: string;
	readonly matchedText: string;
	readonly fullText: string;
}

const MTEXT_TOKEN_REGEX = /(\\[\\{}]|\\[a-zA-Z][^;]*;|\\[a-zA-Z]|\\[~]|\\S[^;]*;|[{}]|[^{}\\]+)/g;

/**
 * Extracts plain text from an MTEXT content string by stripping formatting codes.
 */
export function mtextToPlainText(contents: string): string {
	const tokens = contents.match(MTEXT_TOKEN_REGEX) || [contents];
	const plainTokens: string[] = [];
	for (const token of tokens) {
		if (token === '{' || token === '}') continue;
		if (token.startsWith('\\')) {
			if (token === '\\P') plainTokens.push('\n');
			if (token === '\\~') plainTokens.push(' ');
			continue;
		}
		plainTokens.push(token);
	}
	return plainTokens.join('');
}

/**
 * Replaces matching text occurrences inside MTEXT while keeping all formatting codes intact.
 */
export function replaceInMText(contents: string, regex: RegExp, replacement: string): { newContents: string; count: number } {
	const tokens = contents.match(MTEXT_TOKEN_REGEX) || [contents];
	let count = 0;
	const newTokens = tokens.map(token => {
		if (token === '{' || token === '}' || token.startsWith('\\')) {
			return token;
		}
		const matches = token.match(regex);
		if (matches) {
			count += matches.length;
			return token.replace(regex, replacement);
		}
		return token;
	});
	return { newContents: newTokens.join(''), count };
}

/**
 * Constructs a RegExp from search pattern and options.
 */
export function buildSearchRegex(pattern: string, options: FindOptions = {}): RegExp {
	let body = '';
	if (options.wildcards) {
		// Escape regex special chars except * and ?
		body = pattern.replace(/[-[\]{}()+.,^$|#\s]/g, '\\$&')
			.replace(/\*/g, '.*')
			.replace(/\?/g, '.');
	} else {
		body = pattern.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&');
	}

	if (options.wholeWord) {
		body = `\\b(?:${body})\\b`;
	}

	const flags = options.matchCase ? 'g' : 'gi';
	return new RegExp(body, flags);
}

export interface FindResult {
	readonly matches: readonly FindMatch[];
	readonly totalCount: number;
}

/**
 * Pure search function: finds all text occurrences in the database matching options.
 */
export function findTextInDatabase(db: AcDbDatabase, searchText: string, options: FindOptions = {}): FindResult {
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace || !searchText) {
		return { matches: [], totalCount: 0 };
	}

	const regex = buildSearchRegex(searchText, options);
	const matches: FindMatch[] = [];
	let totalCount = 0;

	for (const ent of modelSpace.newIterator()) {
		const entId = String(ent.objectId);

		if (ent instanceof AcDbText) {
			const str = ent.textString || '';
			const m = str.match(regex);
			if (m) {
				totalCount += m.length;
				matches.push({ entity: ent, entityId: entId, type: 'TEXT', matchedText: m[0], fullText: str });
			}
		} else if (ent instanceof AcDbMText) {
			const plain = mtextToPlainText(ent.contents || '');
			const m = plain.match(regex);
			if (m) {
				totalCount += m.length;
				matches.push({ entity: ent, entityId: entId, type: 'MTEXT', matchedText: m[0], fullText: ent.contents });
			}
		} else if (ent instanceof AcDbAttribute || ent instanceof AcDbAttributeDefinition) {
			const str = ent.textString || '';
			const m = str.match(regex);
			if (m) {
				totalCount += m.length;
				matches.push({ entity: ent, entityId: entId, type: 'ATTRIB', matchedText: m[0], fullText: str });
			}
		} else if (ent instanceof AcDbBlockReference) {
			for (const attr of ent.attributeIterator()) {
				const str = attr.textString || '';
				const m = str.match(regex);
				if (m) {
					totalCount += m.length;
					matches.push({ entity: ent, entityId: entId, type: 'BLOCK_ATTRIB', matchedText: m[0], fullText: str });
				}
			}
		} else if (ent instanceof AcDbDimension) {
			const str = ent.dimensionText;
			if (str && str !== '<>') {
				const m = str.match(regex);
				if (m) {
					totalCount += m.length;
					matches.push({ entity: ent, entityId: entId, type: 'DIMENSION', matchedText: m[0], fullText: str });
				}
			}
		} else if (ent instanceof AcDbTable) {
			const numRows = ent.numRows;
			const numCols = ent.numColumns;
			for (let r = 0; r < numRows; r++) {
				for (let c = 0; c < numCols; c++) {
					const cell = ent.cell(r * numCols + c);
					if (cell?.text) {
						const m = cell.text.match(regex);
						if (m) {
							totalCount += m.length;
							matches.push({ entity: ent, entityId: entId, type: 'TABLE_CELL', matchedText: m[0], fullText: cell.text });
						}
					}
				}
			}
		} else if (ent instanceof AcDbMLeader) {
			const text = ent.mtextContent?.text;
			if (text) {
				const plain = mtextToPlainText(text);
				const m = plain.match(regex);
				if (m) {
					totalCount += m.length;
					matches.push({ entity: ent, entityId: entId, type: 'MLEADER', matchedText: m[0], fullText: text });
				}
			}
		}
	}

	return { matches, totalCount };
}

/**
 * Pure replace function: replaces text occurrences in the database in place.
 */
export function replaceTextInDatabase(
	db: AcDbDatabase,
	searchText: string,
	replaceText: string,
	options: FindOptions = {},
): { replacedOccurrences: number; affectedEntities: number } {
	const modelSpace = db.tables?.blockTable?.modelSpace;
	if (!modelSpace || !searchText) {
		return { replacedOccurrences: 0, affectedEntities: 0 };
	}

	const regex = buildSearchRegex(searchText, options);
	let replacedOccurrences = 0;
	let affectedEntities = 0;

	for (const ent of modelSpace.newIterator()) {
		let entityModified = false;

		if (ent instanceof AcDbText) {
			const str = ent.textString || '';
			const m = str.match(regex);
			if (m) {
				ent.textString = str.replace(regex, replaceText);
				replacedOccurrences += m.length;
				entityModified = true;
			}
		} else if (ent instanceof AcDbMText) {
			const contents = ent.contents || '';
			const res = replaceInMText(contents, regex, replaceText);
			if (res.count > 0) {
				ent.contents = res.newContents;
				replacedOccurrences += res.count;
				entityModified = true;
			}
		} else if (ent instanceof AcDbAttribute || ent instanceof AcDbAttributeDefinition) {
			const str = ent.textString || '';
			const m = str.match(regex);
			if (m) {
				ent.textString = str.replace(regex, replaceText);
				replacedOccurrences += m.length;
				entityModified = true;
			}
		} else if (ent instanceof AcDbBlockReference) {
			for (const attr of ent.attributeIterator()) {
				const str = attr.textString || '';
				const m = str.match(regex);
				if (m) {
					attr.textString = str.replace(regex, replaceText);
					replacedOccurrences += m.length;
					entityModified = true;
				}
			}
		} else if (ent instanceof AcDbDimension) {
			const str = ent.dimensionText;
			if (str && str !== '<>') {
				const m = str.match(regex);
				if (m) {
					ent.dimensionText = str.replace(regex, replaceText);
					replacedOccurrences += m.length;
					entityModified = true;
				}
			}
		} else if (ent instanceof AcDbTable) {
			const numRows = ent.numRows;
			const numCols = ent.numColumns;
			for (let r = 0; r < numRows; r++) {
				for (let c = 0; c < numCols; c++) {
					const cell = ent.cell(r * numCols + c);
					if (cell?.text) {
						const m = cell.text.match(regex);
						if (m) {
							cell.text = cell.text.replace(regex, replaceText);
							replacedOccurrences += m.length;
							entityModified = true;
						}
					}
				}
			}
		} else if (ent instanceof AcDbMLeader) {
			const mtextContent = ent.mtextContent;
			if (mtextContent && mtextContent.text) {
				const res = replaceInMText(mtextContent.text, regex, replaceText);
				if (res.count > 0) {
					ent.mtextContent = {
						text: res.newContents,
						anchorPoint: mtextContent.anchorPoint,
					};
					replacedOccurrences += res.count;
					entityModified = true;
				}
			}
		}

		if (entityModified) {
			affectedEntities++;
		}
	}

	return { replacedOccurrences, affectedEntities };
}

/**
 * Command -FIND: command-line find and replace.
 */
export async function findCommand(ctx: CadCommandContext): Promise<void> {
	const searchText = await ctx.getString('Enter text to find:');
	if (!searchText) return;

	const replaceText = await ctx.getString('Enter replacement text (or press Enter to find only):');
	const matchCaseOpt = await ctx.getKeyword('Match case? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
	const wholeWordOpt = await ctx.getKeyword('Whole words only? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });
	const wildcardsOpt = await ctx.getKeyword('Use wildcards? [Yes/No] <No>:', ['Yes', 'No'], { default: 'No' });

	const options: FindOptions = {
		matchCase: matchCaseOpt.toLowerCase() === 'yes',
		wholeWord: wholeWordOpt.toLowerCase() === 'yes',
		wildcards: wildcardsOpt.toLowerCase() === 'yes',
	};

	if (replaceText !== undefined && replaceText !== '') {
		let result = { replacedOccurrences: 0, affectedEntities: 0 };
		await ctx.transaction(async () => {
			result = replaceTextInDatabase(ctx.database.native, searchText, replaceText, options);
		});
		ctx.message(`Replaced ${result.replacedOccurrences} occurrence(s) across ${result.affectedEntities} object(s).`);
	} else {
		const result = findTextInDatabase(ctx.database.native, searchText, options);
		ctx.message(`Found ${result.totalCount} match(es) across ${result.matches.length} object(s).`);
	}
}

export function registerFindCommands(): void {
	registerCommand('FIND', findCommand);
	registerCommand('-FIND', findCommand);
}
