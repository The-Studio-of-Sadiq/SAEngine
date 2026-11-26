/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. Licensed under the AGPL-3.0-only license.
 *--------------------------------------------------------------------------------------------*/

/**
 * Smoothed shell contours: one value per shell (its centre, or a design value of the shell)
 * turned into one value per corner, the mean of the values of the shells that share that node.
 * Drawn with a colour per corner, the colours blend across each shell, as ETABS draws its
 * smoothed contours. Only the shells of one member are averaged together (the shells of one name
 * before `#`: a slab `S1`, `S1#2`, ... or a wall), so a slab does not blur into the wall or the
 * slab it meets.
 */

export interface ContourShell {
	readonly name?: string;
	readonly nodes: readonly number[];
}

/** The member an analysis element (a shell or a frame piece) belongs to: its name before `#` (the whole name when it has none). */
export function memberName(name: string | undefined): string {
	const text = name ?? '';
	const at = text.indexOf('#');
	return at < 0 ? text : text.slice(0, at);
}

/**
 * Per shell, the value at each of its corners (in the order of its nodes): the mean of `values`
 * over the shells of the same member that have that node. `values[i]` belongs to `shells[i]`.
 */
export function cornerValues(shells: readonly ContourShell[], values: readonly number[]): number[][] {
	const sums = new Map<string, { sum: number; count: number }>();
	const key = (member: string, node: number) => `${member}\u0000${node}`;
	shells.forEach((shell, i) => {
		const member = memberName(shell.name);
		for (const node of shell.nodes) {
			const k = key(member, node);
			const entry = sums.get(k);
			if (entry) {
				entry.sum += values[i];
				entry.count++;
			} else {
				sums.set(k, { sum: values[i], count: 1 });
			}
		}
	});
	return shells.map(shell => {
		const member = memberName(shell.name);
		return shell.nodes.map(node => {
			const entry = sums.get(key(member, node))!;
			return entry.sum / entry.count;
		});
	});
}
