(() => {
	const vscode = acquireVsCodeApi();
	const canvas = document.getElementById('structure-view');
	const context = canvas.getContext('2d');
	const stats = document.getElementById('model-stats');
	const modelName = document.getElementById('model-name');

	let project;
	let yaw = -0.72;
	let pitch = 0.36;
	let zoom = 1;
	let drag;
	let animationFrame;

	function starterProject() {
		const makeGrid = (label, position) => ({
			id: `${label}-${position}`,
			label,
			position,
			is_visible: true,
		});
		const stories = [{ name: 'Base', elevation: 0, height: 0, is_base: true }];
		for (let level = 1; level <= 4; level++) {
			stories.push({
				name: level === 4 ? 'Roof' : `Story ${level}`,
				elevation: level * 3,
				height: 3,
				is_base: false,
			});
		}
		return {
			settings: { project_name: 'Starter Building' },
			grids: {
				x_grids: [0, 6, 12, 18].map((position, index) =>
					makeGrid(String(index + 1), position),
				),
				y_grids: [0, 6, 12].map((position, index) =>
					makeGrid(String.fromCharCode(65 + index), position),
				),
			},
			stories: { stories },
			frame_model: { joints: [], members: [] },
		};
	}

	function buildGeometry(model) {
		const frame = model.frame_model;
		if (frame && frame.joints?.length && frame.members?.length) {
			const nodes = new Map(frame.joints.map(node => [node.id, {
				id: node.id,
				position: node.coordinates.map(Number),
			}]));
			const members = frame.members.map(member => ({
				start: nodes.get(member.start_joint),
				end: nodes.get(member.end_joint),
			})).filter(member => member.start && member.end);
			return { nodes: [...nodes.values()], members };
		}

		const xCoordinates = (model.grids?.x_grids || [])
			.map(grid => Number(grid.position))
			.filter(Number.isFinite);
		const yCoordinates = (model.grids?.y_grids || [])
			.map(grid => Number(grid.position))
			.filter(Number.isFinite);
		const elevations = (model.stories?.stories || [])
			.map(story => Number(story.elevation))
			.filter(Number.isFinite);
		if (!xCoordinates.length || !yCoordinates.length || elevations.length < 2) {
			return { nodes: [], members: [] };
		}
		const levels = [...new Set(elevations)].sort((a, b) => a - b);
		const xs = [...new Set(xCoordinates)].sort((a, b) => a - b);
		const ys = [...new Set(yCoordinates)].sort((a, b) => a - b);
		const nodes = [];
		const lookup = new Map();
		for (let level = 0; level < levels.length; level++) {
			for (let iy = 0; iy < ys.length; iy++) {
				for (let ix = 0; ix < xs.length; ix++) {
					const node = {
						id: nodes.length + 1,
						position: [xs[ix], ys[iy], levels[level]],
						level,
						ix,
						iy,
					};
					nodes.push(node);
					lookup.set(`${level}:${iy}:${ix}`, node);
				}
			}
		}
		const members = [];
		function connect(a, b) {
			members.push({ start: a, end: b });
		}
		for (let level = 0; level < levels.length - 1; level++) {
			for (let iy = 0; iy < ys.length; iy++) {
				for (let ix = 0; ix < xs.length; ix++) {
					connect(lookup.get(`${level}:${iy}:${ix}`), lookup.get(`${level + 1}:${iy}:${ix}`));
				}
			}
		}
		for (let level = 1; level < levels.length; level++) {
			for (let iy = 0; iy < ys.length; iy++) {
				for (let ix = 0; ix < xs.length - 1; ix++) {
					connect(lookup.get(`${level}:${iy}:${ix}`), lookup.get(`${level}:${iy}:${ix + 1}`));
				}
			}
			for (let ix = 0; ix < xs.length; ix++) {
				for (let iy = 0; iy < ys.length - 1; iy++) {
					connect(lookup.get(`${level}:${iy}:${ix}`), lookup.get(`${level}:${iy + 1}:${ix}`));
				}
			}
		}
		return { nodes, members, xs, ys, levels };
	}

	function draw() {
		animationFrame = undefined;
		const bounds = canvas.getBoundingClientRect();
		if (!bounds.width || !bounds.height) {
			return;
		}
		const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
		const width = Math.round(bounds.width * pixelRatio);
		const height = Math.round(bounds.height * pixelRatio);
		if (canvas.width !== width || canvas.height !== height) {
			canvas.width = width;
			canvas.height = height;
		}
		context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
		context.clearRect(0, 0, bounds.width, bounds.height);
		if (!project) {
			return;
		}

		const geometry = buildGeometry(project);
		if (!geometry.nodes.length || !geometry.members.length) {
			if (stats) {
				stats.textContent = 'No frame geometry';
			}
			if (modelName) {
				modelName.textContent = project.settings?.project_name || 'SAEngine project';
			}
			drawCompass(bounds);
			return;
		}

		const points = geometry.nodes.map(node => node.position);
		const minimum = [0, 1, 2].map(axis => Math.min(...points.map(point => point[axis])));
		const maximum = [0, 1, 2].map(axis => Math.max(...points.map(point => point[axis])));
		const center = minimum.map((value, axis) => (value + maximum[axis]) / 2);
		const span = minimum.map((value, axis) => Math.max(maximum[axis] - value, 1));
		const rotate = position => {
			const x = (position[0] - center[0]) / span[0];
			const y = (position[1] - center[1]) / span[1];
			const z = (position[2] - center[2]) / span[2];
			const cosine = Math.cos(yaw);
			const sine = Math.sin(yaw);
			const horizontal = x * cosine - y * sine;
			const depth = x * sine + y * cosine;
			return {
				x: horizontal,
				y: z * Math.cos(pitch) - depth * Math.sin(pitch),
				depth: depth * Math.cos(pitch) + z * Math.sin(pitch),
			};
		};
		const corners = [];
		for (const x of [-0.5, 0.5]) {
			for (const y of [-0.5, 0.5]) {
				for (const z of [-0.5, 0.5]) {
					corners.push(rotate([x, y, z]));
				}
			}
		}
		const plotWidth = bounds.width * 0.77;
		const plotHeight = bounds.height * 0.78;
		const scale = Math.min(
			plotWidth / (Math.max(...corners.map(point => point.x)) - Math.min(...corners.map(point => point.x))),
			plotHeight / (Math.max(...corners.map(point => point.y)) - Math.min(...corners.map(point => point.y))),
		) * zoom;
		const screenCenterX = bounds.width * 0.51;
		const screenCenterY = bounds.height * 0.51;
		const projectPoint = position => {
			const point = rotate(position);
			const perspective = 1 / (1 + point.depth * 0.12);
			return {
				x: screenCenterX + point.x * scale * perspective,
				y: screenCenterY - point.y * scale * perspective,
				depth: point.depth,
			};
		};

		function drawCompass(viewBounds) {
			const origin = { x: 45, y: viewBounds.height - 48 };
			const axisLength = 24;
			const cosine = Math.cos(yaw);
			const sine = Math.sin(yaw);
			const directions = [
				{ vector: [1, 0, 0], positive: 'E', negative: 'W', color: '#ef8e89' },
				{ vector: [0, 1, 0], positive: 'N', negative: 'S', color: '#8fd19a' },
				{ vector: [0, 0, 1], positive: 'UP', negative: 'DOWN', color: '#77c9f1' },
			];
			const rotateDirection = ([x, y, z]) => ({
				x: x * cosine - y * sine,
				y: z * Math.cos(pitch) - (x * sine + y * cosine) * Math.sin(pitch),
			});

			context.save();
			context.font = '600 9px "Segoe UI", sans-serif';
			context.textAlign = 'center';
			context.textBaseline = 'middle';
			context.lineWidth = 1.6;
			for (const direction of directions) {
				const end = rotateDirection(direction.vector);
				const first = {
					x: origin.x - end.x * axisLength,
					y: origin.y + end.y * axisLength,
				};
				const second = {
					x: origin.x + end.x * axisLength,
					y: origin.y - end.y * axisLength,
				};
				context.beginPath();
				context.moveTo(first.x, first.y);
				context.lineTo(second.x, second.y);
				context.strokeStyle = direction.color;
				context.globalAlpha = .82;
				context.stroke();
				context.fillStyle = direction.color;
				context.globalAlpha = 1;
				context.fillText(direction.negative, first.x, first.y);
				context.fillText(direction.positive, second.x, second.y);
			}
			context.beginPath();
			context.arc(origin.x, origin.y, 3, 0, Math.PI * 2);
			context.fillStyle = '#edf3f7';
			context.fill();
			context.restore();
		}

		function strokeMember(member, color, alpha, lineWidth) {
			const first = projectPoint(member.start.position);
			const second = projectPoint(member.end.position);
			context.beginPath();
			context.moveTo(first.x, first.y);
			context.lineTo(second.x, second.y);
			context.strokeStyle = color;
			context.globalAlpha = alpha;
			context.lineWidth = lineWidth;
			context.lineCap = 'round';
			context.stroke();
			return (first.depth + second.depth) / 2;
		}

		context.save();
		context.lineWidth = 1;
		{
			const ground = minimum[2];
			const base = [
				[minimum[0], minimum[1], ground],
				[maximum[0], minimum[1], ground],
				[maximum[0], maximum[1], ground],
				[minimum[0], maximum[1], ground],
			].map(projectPoint);
			context.beginPath();
			context.moveTo(base[0].x, base[0].y);
			for (const corner of base.slice(1)) {
				context.lineTo(corner.x, corner.y);
			}
			context.closePath();
			context.fillStyle = '#55cfbe';
			context.globalAlpha = .045;
			context.fill();
			context.strokeStyle = '#55cfbe';
			context.globalAlpha = .24;
			context.stroke();

			const divisions = 6;
			for (let index = 0; index <= divisions; index++) {
				const fraction = index / divisions;
				const x = minimum[0] + fraction * span[0];
				const y = minimum[1] + fraction * span[1];
				for (const axis of [0, 1]) {
					const first = axis === 0
						? [x, minimum[1], ground]
						: [minimum[0], y, ground];
					const second = axis === 0
						? [x, maximum[1], ground]
						: [maximum[0], y, ground];
					const a = projectPoint(first);
					const b = projectPoint(second);
					context.beginPath();
					context.moveTo(a.x, a.y);
					context.lineTo(b.x, b.y);
					context.strokeStyle = '#33424e';
					context.globalAlpha = .16;
					context.stroke();
				}
			}
		}

		const sortedMembers = geometry.members.map(member => {
			const vertical = Math.abs(member.start.position[2] - member.end.position[2])
				> Math.max(span[2] * 0.001, 1e-9);
			return {
				member,
				vertical,
				depth: (projectPoint(member.start.position).depth
					+ projectPoint(member.end.position).depth) / 2,
			};
		}).sort((a, b) => a.depth - b.depth);
		for (const { member, vertical, depth } of sortedMembers) {
			const emphasis = Math.max(.42, Math.min(.9, .69 + depth * .16));
			strokeMember(
				member,
				vertical ? '#66b9b5' : '#54d7c6',
				emphasis,
				vertical ? 2.1 : 1.65,
			);
		}

		context.restore();
		drawCompass(bounds);
		if (stats) {
			stats.textContent = `${geometry.nodes.length} joints  ·  ${geometry.members.length} members  ·  ${geometry.levels?.length - 1 || Math.max(1, new Set(points.map(point => point[2])).size - 1)} stories`;
		}
		if (modelName) {
			modelName.textContent = project.settings?.project_name || 'SAEngine project';
		}
	}

	function scheduleDraw() {
		if (animationFrame === undefined) {
			animationFrame = window.requestAnimationFrame(draw);
		}
	}

	canvas.addEventListener('pointerdown', event => {
		drag = { x: event.clientX, y: event.clientY };
		canvas.setPointerCapture(event.pointerId);
	});
	canvas.addEventListener('pointermove', event => {
		if (!drag) {
			return;
		}
		yaw += (event.clientX - drag.x) * .008;
		pitch = Math.max(-.2, Math.min(1.15, pitch + (event.clientY - drag.y) * .006));
		drag = { x: event.clientX, y: event.clientY };
		scheduleDraw();
	});
	canvas.addEventListener('pointerup', () => { drag = undefined; });
	canvas.addEventListener('pointercancel', () => { drag = undefined; });
	canvas.addEventListener('wheel', event => {
		event.preventDefault();
		zoom = Math.max(.5, Math.min(2.5, zoom * Math.exp(-event.deltaY * .001)));
		scheduleDraw();
	}, { passive: false });
	document.getElementById('reset-view')?.addEventListener('click', () => {
		yaw = -.72;
		pitch = .36;
		zoom = 1;
		scheduleDraw();
	});
	document.getElementById('create-project')?.addEventListener('click', () => {
		vscode.postMessage({ command: 'createProject' });
	});
	document.getElementById('open-project')?.addEventListener('click', () => {
		vscode.postMessage({ command: 'openProject' });
	});
	window.addEventListener('message', event => {
		if (event.data?.command === 'project') {
			project = event.data.project;
			yaw = -.72;
			pitch = .36;
			zoom = 1;
			scheduleDraw();
		}
	});
	new ResizeObserver(scheduleDraw).observe(canvas);
	project = starterProject();
	scheduleDraw();
	vscode.postMessage({ command: 'ready' });
})();
