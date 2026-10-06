import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

// Exercise the actual modal callbacks without starting React Native or a phone.
const source = readFileSync(new URL('../src/components/QuickOrderModal.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, esModuleInterop: true,
} }).outputText;

function setup(text = '', busy = false, enabled = true) {
  let closes = 0;
  let result;
  const toasts = [];
  let hookIndex = 0;
  const hooks = [];
  const quickOrders = { text, submitting: busy, isSubmitting: () => busy,
    submit: async () => result,
    setText: value => { quickOrders.text = value; } };
  const exports = {};
  const react = { createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
    useRef(value) { const i = hookIndex++; return hooks[i] ??= { current: value }; },
    useState(value) { const i = hookIndex++; hooks[i] ??= value;
      return [hooks[i], next => { hooks[i] = next; }]; },
    useEffect() {} };
  vm.runInNewContext(compiled, { exports, require(name) {
    if (name === 'react') return react;
    if (name === 'react-native') return { Modal: 'Modal', View: 'View', Pressable: 'Pressable',
      KeyboardAvoidingView: 'KeyboardAvoidingView', ScrollView: 'ScrollView', Text: 'Text', TextInput: 'TextInput',
      Platform: { OS: 'android' }, Keyboard: { dismiss() {} } };
    if (name.includes('OrderFlowProvider')) return { useOrderFlow: () => ({ quickOrders, quickOrdersEnabled: enabled }) };
    if (name.includes('quickOrderFlow')) return { QUICK_ORDER_TEXT_LIMIT: 5000 };
    if (name.includes('appStyles')) return { styles: {}, colors: {} };
    if (name === './orderUi') return { FeedbackPressable: 'Button' };
    if (name === 'react-native-toast-message') return { show: value => toasts.push(value) };
    throw new Error(name);
  } });
  function render() {
    hookIndex = 0;
    return exports.QuickOrderModal({ visible: true, onClose: () => { closes++; } });
  }
  function warning() { return render().children[0].children[2]; }
  const tree = render();
  const overlay = tree.children[0];
  return { tree, warning, quickOrders, closes: () => closes, toasts,
    setResult: value => { result = value; },
    submit: () => exports.QuickOrderForm({ onSubmitted: () => { closes++; } }).children[4].props.onPress(),
    dismiss: [tree.props.onRequestClose, overlay.children[0].props.onPress,
      overlay.children[1].children[0].children[1].children[1].props.onPress] };
}

test('outside, close button and Android Back protect drafts with themed actions', () => {
  for (const path of [0, 1, 2]) {
    const flow = setup('Item A, 3');
    flow.dismiss[path]();
    assert.equal(flow.closes(), 0);
    const card = flow.warning().children[1];
    assert.equal(card.children[2].children[0].children[0].children[0], 'Keep Editing');
    card.children[2].children[0].props.onPress();
    assert.equal(flow.warning(), false);
    assert.equal(flow.quickOrders.text, 'Item A, 3');
    flow.dismiss[path]();
    flow.warning().children[1].children[2].children[1].props.onPress();
    assert.equal(flow.quickOrders.text, '');
    assert.equal(flow.closes(), 1);
  }
});

test('empty drafts close directly and submissions block dismissal', () => {
  const empty = setup();
  empty.dismiss[0]();
  assert.equal(empty.closes(), 1);
  assert.equal(empty.warning(), false);
  const busy = setup('Item A', true);
  busy.dismiss.forEach(dismiss => dismiss());
  assert.equal(busy.closes(), 0);
  assert.equal(busy.warning(), false);
});

test('warning backdrop and Android Back return to editing without losing text', () => {
  const flow = setup('Item A');
  flow.dismiss[0]();
  flow.warning().children[0].props.onPress();
  assert.equal(flow.warning(), false);
  flow.dismiss[0]();
  flow.dismiss[0]();
  assert.equal(flow.warning(), false);
  assert.equal(flow.closes(), 0);
  assert.equal(flow.quickOrders.text, 'Item A');
});

test('modal is hidden when customer access is unavailable', () => {
  assert.equal(setup('', false, false).tree.props.visible, false);
});

test('successful submission closes the form and shows a brief toast', async () => {
  const flow = setup('Item A');
  flow.setResult({ name: 'KE-QOR-123' });
  await flow.submit();
  assert.equal(flow.closes(), 1);
  assert.equal(flow.toasts.length, 1);
  assert.equal(flow.toasts[0].text1, 'Request sent');
});

test('failed or superseded submissions keep the form open without a success toast', async () => {
  const flow = setup('Item A');
  await flow.submit();
  assert.equal(flow.closes(), 0);
  assert.equal(flow.toasts.length, 0);
  assert.equal(flow.quickOrders.text, 'Item A');
});
