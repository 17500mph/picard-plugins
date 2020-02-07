# Enhanced Title Case Plugin (Work in Progress)

## What it does:

A new scripting command is added `$titlecase`. 

All Words Not in the List of Exceptions Are Capitalized.

Existing CaPiTaLs are retained. 

### Goofy Text String Example:

This Grammatically Atrocious Sentence:

the traveling prayers at the small stadium in the woods near o'reilly forest by the lake feat billy joel and the beatles with the who plus devo and abba mocking PhoolishPhloyd at the US festival in the USA.

Becomes:

The Traveling Prayers at the Small Stadium in the Woods Near O'Reilly Forest by the Lake feat Billy Joel and the Beatles With the Who Plus DEVO and ABBA Mocking PhoolishPhloyd at the US Festival in the USA


## Configuration Notes.

There are three fields and a tick-box in `Options: Plugins: Enhanced Title Case`

The tick-box is a bonus. It does nothing.

The first field is for words to be converted to ALL UPPER CASE.

Enter comma separated values. [`ABBA, AC/DC, DEVO, MECO`]

The second field is for words that will remain lower case. Note: These are separated by the `|` (pipe) character and are not spaced.

The default string is:

[`a|an|and|as|at|but|by|en|for|feat|if|in|of|on|or|the|to|v\.?|via|vs\.?`]

The third field is non-functional. (Feature Coming Soon, Hopefully)

## To Be Done:

• Figure out how to make the configuration fields each be on a new line.

• Add text above each one of them

• Add in Exception for Artist Intent Titles, 'The Beatles', 'The Who', 'Ludwig van Beethoven', etc.

