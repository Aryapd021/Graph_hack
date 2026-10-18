import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { Send, Bot, User, Sparkles, AlertTriangle, Loader2 } from 'lucide-react';
import { api, ApiError, type ChatTurn, type Evidence } from '../api/client';
import { useBrainStore } from '../store/brainStore';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: Evidence[];
}

const STARTER_PROMPTS = [
  "Which decisions need review?",
  "Who owns docs/en/docs?",
  "Who knows the most about Additional Status Codes?",
  "Why did we decide Implement structured request lifecycle telemetry in tests?",
  "Is that decision still valid? Implement structured request lifecycle telemetry in tests",
  "Who are the key connectors?",
];

export const ChatPanel: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '👋 Welcome to **Company Brain**! I use FalkorDB knowledge graphs and live tools to answer questions about architecture decisions, team ownership, drift, and key collaborators.\n\nAsk a question or pick one below to get started!',
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [rateLimitNotice, setRateLimitNotice] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const mergeGraph = useBrainStore((state) => state.mergeGraph);
  const setHighlight = useBrainStore((state) => state.setHighlight);
  const setLatestTrace = useBrainStore((state) => state.setLatestTrace);
  const setSelectedNodeId = useBrainStore((state) => state.setSelectedNodeId);
  const setRightTab = useBrainStore((state) => state.setRightTab);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSend = async (messageText?: string) => {
    const textToSend = (messageText || input).trim();
    if (!textToSend || isLoading) return;

    setInput('');
    setChatError(null);
    setRateLimitNotice(null);

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: textToSend,
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      // Build conversation history for agent (max 10 turns)
      const historyTurns: ChatTurn[] = messages
        .filter((m) => m.id !== 'welcome')
        .slice(-10)
        .map((m) => ({
          role: m.role,
          content: m.content,
        }));

      const res = await api.sendChat({
        message: textToSend,
        history: historyTurns,
      });

      // Update state per specification
      if (res.graph) {
        mergeGraph(res.graph);
      }
      if (res.highlight) {
        setHighlight(res.highlight);
      }
      if (res.trace) {
        setLatestTrace(res.trace);
        setRightTab('trace');
      }

      const botMsg: Message = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: res.answer,
        citations: res.citations,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 429 || err.code === 'RATE_LIMITED') {
          setRateLimitNotice('Rate limit reached (10 requests/min). Please slow down and try again in a moment.');
        } else {
          setChatError(err.message);
        }
      } else if (err instanceof Error) {
        setChatError(err.message);
      } else {
        setChatError('An unexpected error occurred while communicating with Company Brain.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  // Render markdown text and replace [[node_id]] markers with clickable citation chips
  const renderMessageContent = (content: string, citations?: Evidence[]) => {
    const citationMap = new Map(citations?.map((c) => [c.node_id, c]));

    // Match [[node_id]] markers
    const parts: React.ReactNode[] = [];
    const regex = /\[\[(.*?)\]\]/g;
    let lastIndex = 0;
    let match;

    while ((match = regex.exec(content)) !== null) {
      const matchIndex = match.index;
      const markerId = match[1].trim();

      // Push text prior to match
      if (matchIndex > lastIndex) {
        parts.push(
          <ReactMarkdown
            key={`md-${lastIndex}`}
            className="prose prose-invert prose-sm max-w-none inline prose-p:my-1 prose-ul:my-1 prose-li:my-0.5"
          >
            {content.substring(lastIndex, matchIndex)}
          </ReactMarkdown>
        );
      }

      // Check if markerId exists in citations
      const evidence = citationMap.get(markerId);
      if (evidence) {
        parts.push(
          <button
            key={`chip-${matchIndex}-${markerId}`}
            onClick={() => {
              setSelectedNodeId(markerId);
              setRightTab('node');
            }}
            className="inline-flex items-center gap-1 mx-1 px-2 py-0.5 rounded-full text-xs font-mono font-medium bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 border border-amber-500/40 transition-colors shadow-sm"
            title={`View ${evidence.label}: ${evidence.display} (${evidence.node_id})`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span>{evidence.display || markerId}</span>
          </button>
        );
      }
      // Unknown markers are simply excluded (removed) per Section 12 rule 4

      lastIndex = regex.lastIndex;
    }

    if (lastIndex < content.length) {
      parts.push(
        <ReactMarkdown
          key={`md-end-${lastIndex}`}
          className="prose prose-invert prose-sm max-w-none inline prose-p:my-1 prose-ul:my-1 prose-li:my-0.5"
        >
          {content.substring(lastIndex)}
        </ReactMarkdown>
      );
    }

    return <div>{parts}</div>;
  };

  return (
    <div className="flex flex-col h-full bg-slate-900/60 border-r border-slate-800">
      {/* Header */}
      <div className="p-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-900/40">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-emerald-400" />
          <h2 className="text-sm font-semibold tracking-wide text-slate-200">Company Brain AI</h2>
        </div>
        <span className="text-xs font-mono text-slate-500">Autonomous MCP Agent</span>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex items-start gap-3 ${
              msg.role === 'user' ? 'justify-end' : 'justify-start'
            }`}
          >
            {msg.role === 'assistant' && (
              <div className="w-7 h-7 rounded-lg bg-emerald-950/80 border border-emerald-700/60 flex items-center justify-center shrink-0 shadow-sm mt-0.5">
                <Bot className="w-4 h-4 text-emerald-400" />
              </div>
            )}

            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-md ${
                msg.role === 'user'
                  ? 'bg-emerald-600 text-white rounded-tr-none font-normal'
                  : 'bg-slate-850 border border-slate-800 text-slate-200 rounded-tl-none'
              }`}
            >
              {msg.role === 'user' ? (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              ) : (
                renderMessageContent(msg.content, msg.citations)
              )}
            </div>

            {msg.role === 'user' && (
              <div className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center shrink-0 shadow-sm mt-0.5">
                <User className="w-4 h-4 text-slate-300" />
              </div>
            )}
          </div>
        ))}

        {isLoading && (
          <div className="flex items-start gap-3">
            <div className="w-7 h-7 rounded-lg bg-emerald-950/80 border border-emerald-700/60 flex items-center justify-center shrink-0 mt-0.5 animate-pulse">
              <Sparkles className="w-4 h-4 text-emerald-400 animate-spin" />
            </div>
            <div className="bg-slate-850 border border-slate-800 rounded-2xl rounded-tl-none px-4 py-3 text-sm text-slate-300 flex items-center gap-2.5">
              <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
              <span className="font-mono text-xs text-slate-400">
                Reasoning over FalkorDB graph via MCP tools...
              </span>
            </div>
          </div>
        )}

        {/* Transient Rate Limit Warning */}
        {rateLimitNotice && (
          <div className="p-3 bg-amber-950/40 border border-amber-800 rounded-xl flex items-center gap-2 text-xs text-amber-300 shadow-sm animate-fade-in">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400" />
            <span>{rateLimitNotice}</span>
          </div>
        )}

        {/* Generic Error Warning */}
        {chatError && (
          <div className="p-3 bg-rose-950/40 border border-rose-800 rounded-xl flex items-center gap-2 text-xs text-rose-300 shadow-sm animate-fade-in">
            <AlertTriangle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{chatError}</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Starter Suggestions */}
      {messages.length <= 2 && (
        <div className="px-4 py-2 border-t border-slate-800/60 bg-slate-900/30">
          <div className="flex items-center gap-1.5 mb-2 text-xs font-mono text-slate-400">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>Suggested Questions:</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {STARTER_PROMPTS.map((prompt, i) => (
              <button
                key={i}
                onClick={() => handleSend(prompt)}
                disabled={isLoading}
                className="text-xs text-left px-2.5 py-1.5 rounded-lg bg-slate-800/80 hover:bg-slate-750 border border-slate-700/80 text-slate-300 hover:text-white transition-all duration-150 disabled:opacity-50"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input Area */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSend();
        }}
        className="p-3.5 border-t border-slate-800 bg-slate-900/60"
      >
        <div className="relative flex items-center">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about decisions, module ownership, or drift..."
            disabled={isLoading}
            className="w-full bg-slate-850 border border-slate-700/80 rounded-xl pl-4 pr-11 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="absolute right-2 p-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-30 disabled:hover:bg-emerald-600 transition-colors shadow-sm"
            aria-label="Send message"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </form>
    </div>
  );
};
